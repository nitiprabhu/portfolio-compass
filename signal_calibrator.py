#!/usr/bin/env python3
"""
SIGNAL CALIBRATOR — Self-Correcting Feedback Loop
===================================================
Learns from closed trade outcomes to re-weight the 6 technical scoring layers.

Flow:
  outcomes table (closed trades with tech_layer_snapshot)
      ↓
  LogisticRegression fit (regularised C=0.1)
      ↓
  layer_weights table (persisted for recommendation_engine to load)

Safety: Only trains when n_samples >= MIN_SAMPLES (30).
"""

import json
import numpy as np
from typing import Dict, Optional, Tuple
from database import RecommendationDB

# Minimum closed trades required before we trust learned weights
MIN_SAMPLES = 30

# Layer names in the order they appear in the snapshot
LAYER_NAMES = ["l_trend", "l_momentum", "l_volatility", "l_volume", "l_rs", "l_guards"]
WEIGHT_KEYS = ["w_trend", "w_momentum", "w_volatility", "w_volume", "w_rs", "w_guards"]


class SignalCalibrator:
    """Learns optimal weights for the 6 technical scoring layers."""

    def __init__(self, db: Optional[RecommendationDB] = None):
        self.db = db or RecommendationDB()

    def train(self) -> Dict:
        """
        Train logistic regression on closed outcomes.

        Returns:
            Dict with keys: weights (dict), n_samples (int), accuracy (float),
            diagnostics (dict with MAE/MFE stats), or error info.
        """
        data = self.db.get_calibration_data()

        if len(data) < MIN_SAMPLES:
            return {
                "status": "insufficient_data",
                "n_samples": len(data),
                "min_required": MIN_SAMPLES,
                "message": f"Need {MIN_SAMPLES - len(data)} more closed trades before calibration."
            }

        # Build feature matrix and target vector
        X = []
        y = []
        mae_list = []
        mfe_list = []

        for row in data:
            snapshot = row.get("tech_layer_snapshot")
            if not snapshot or not isinstance(snapshot, dict):
                continue

            features = [snapshot.get(name, 0.0) for name in LAYER_NAMES]
            X.append(features)

            # Target: 1 if profitable (HIT_TARGET or positive return), 0 otherwise
            is_win = row["status"] == "HIT_TARGET" or (row.get("return_pct", 0) or 0) > 0
            y.append(1 if is_win else 0)

            # Collect MAE/MFE for diagnostics
            if row.get("max_adverse_excursion") is not None:
                mae_list.append(row["max_adverse_excursion"])
            if row.get("max_favorable_excursion") is not None:
                mfe_list.append(row["max_favorable_excursion"])

        if len(X) < MIN_SAMPLES:
            return {
                "status": "insufficient_valid_data",
                "n_samples": len(X),
                "min_required": MIN_SAMPLES
            }

        X = np.array(X, dtype=float)
        y = np.array(y, dtype=float)

        # Fit logistic regression (regularised to prevent overfitting on small samples)
        try:
            from sklearn.linear_model import LogisticRegression
            from sklearn.preprocessing import StandardScaler

            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)

            model = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
            model.fit(X_scaled, y)

            # Extract coefficients as weights (normalised to mean=1.0)
            raw_weights = model.coef_[0]
            # Shift to positive range and normalise around 1.0
            abs_weights = np.abs(raw_weights)
            if abs_weights.sum() > 0:
                norm_weights = abs_weights / abs_weights.mean()
            else:
                norm_weights = np.ones(len(WEIGHT_KEYS))

            # Preserve sign: if coefficient is negative, the layer is anti-predictive
            for i, rw in enumerate(raw_weights):
                if rw < 0:
                    norm_weights[i] *= -1

            weights = {k: round(float(w), 4) for k, w in zip(WEIGHT_KEYS, norm_weights)}

            # Accuracy on training set (simple measure for logging)
            accuracy = float(model.score(X_scaled, y))

        except ImportError:
            # sklearn not available — fall back to correlation-based weights
            print("⚠️ scikit-learn not installed. Using correlation-based weights.")
            weights, accuracy = self._correlation_weights(X, y)

        # MAE / MFE diagnostics
        diagnostics = {}
        if mae_list:
            diagnostics["avg_mae_pct"] = round(float(np.mean(mae_list)), 2)
            diagnostics["median_mae_pct"] = round(float(np.median(mae_list)), 2)
        if mfe_list:
            diagnostics["avg_mfe_pct"] = round(float(np.mean(mfe_list)), 2)
            diagnostics["median_mfe_pct"] = round(float(np.median(mfe_list)), 2)
        if mae_list and mfe_list:
            diagnostics["mfe_mae_ratio"] = round(float(np.mean(mfe_list)) / max(float(np.mean(mae_list)), 0.01), 2)
            diagnostics["stop_quality"] = "GOOD" if diagnostics["mfe_mae_ratio"] > 2.0 else (
                "OK" if diagnostics["mfe_mae_ratio"] > 1.0 else "NEEDS_TIGHTENING"
            )

        # Persist to database
        self.db.save_layer_weights(weights, len(X), accuracy)

        return {
            "status": "trained",
            "weights": weights,
            "n_samples": len(X),
            "accuracy": round(accuracy, 4),
            "win_rate": round(float(y.mean()), 4),
            "diagnostics": diagnostics
        }

    def _correlation_weights(self, X: np.ndarray, y: np.ndarray) -> Tuple[Dict, float]:
        """Fallback: use Pearson correlation as proxy for feature importance."""
        correlations = []
        for i in range(X.shape[1]):
            col = X[:, i]
            if col.std() == 0:
                correlations.append(0.0)
            else:
                correlations.append(float(np.corrcoef(col, y)[0, 1]))

        abs_corr = np.abs(correlations)
        if abs_corr.sum() > 0:
            norm = abs_corr / abs_corr.mean()
        else:
            norm = np.ones(len(WEIGHT_KEYS))

        # Preserve sign
        for i, c in enumerate(correlations):
            if c < 0:
                norm[i] *= -1

        weights = {k: round(float(w), 4) for k, w in zip(WEIGHT_KEYS, norm)}
        # Rough accuracy estimate
        threshold = 0.5
        preds = (X @ np.array(list(weights.values()))) > np.median(X @ np.array(list(weights.values())))
        accuracy = float(np.mean(preds == y))

        return weights, accuracy

    def get_current_weights(self) -> Dict:
        """
        Load the current weights from DB.
        Returns equal weights (1.0) if no trained weights exist.
        """
        row = self.db.get_latest_layer_weights()
        if row:
            return {
                "w_trend": row.get("w_trend", 1.0),
                "w_momentum": row.get("w_momentum", 1.0),
                "w_volatility": row.get("w_volatility", 1.0),
                "w_volume": row.get("w_volume", 1.0),
                "w_rs": row.get("w_rs", 1.0),
                "w_guards": row.get("w_guards", 1.0),
                "n_samples": row.get("n_samples", 0),
                "accuracy": row.get("accuracy", 0.0),
                "source": "learned"
            }
        return {
            "w_trend": 1.0, "w_momentum": 1.0, "w_volatility": 1.0,
            "w_volume": 1.0, "w_rs": 1.0, "w_guards": 1.0,
            "n_samples": 0, "accuracy": 0.0,
            "source": "default"
        }


if __name__ == "__main__":
    calibrator = SignalCalibrator()
    result = calibrator.train()
    print(json.dumps(result, indent=2))
