"""
model.py - Calibrated Machine Learning Recovery Model with Feature Interactions.
Razorpay Buildathon Track 3: AI Revenue Recovery Agent
"""

import os
import logging
from typing import Dict, Any, Tuple, Optional
import pandas as pd
import numpy as np
import joblib

from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss

from constants import ORACLE_PROBS, HARD_DECLINE_CODES
from simulate import DATASET_PATH, generate_batch

logger = logging.getLogger("recovery_agent.model")

MODEL_PATH = os.path.join(os.path.dirname(__file__), "recovery_model.pkl")

_CACHED_MODEL: Optional[Pipeline] = None


def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    """Prepares features and non-linear interactions without pickling top-level closures."""
    df_out = pd.DataFrame()
    df_out["error_code"] = df["error_code"].astype(str)
    df_out["method"] = df.get("method", pd.Series(["card"] * len(df))).astype(str)
    df_out["error_method"] = df_out["error_code"] + "_" + df_out["method"]
    
    amount_inr = df["amount_inr"].astype(float)
    df_out["amount_inr"] = amount_inr
    df_out["log_amount"] = np.log1p(amount_inr)
    df_out["prior_failures"] = df["prior_failures"].astype(float)
    return df_out


def build_pipeline() -> Pipeline:
    """Constructs a standard scikit-learn Pipeline with ColumnTransformer."""
    categorical_features = ["error_code", "method", "error_method"]
    numeric_features = ["amount_inr", "log_amount", "prior_failures"]

    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_features),
            ("num", StandardScaler(), numeric_features),
        ]
    )

    base_gbm = HistGradientBoostingClassifier(
        max_iter=150,
        max_depth=5,
        learning_rate=0.08,
        random_state=42,
    )

    calibrated_clf = CalibratedClassifierCV(
        estimator=base_gbm,
        method="isotonic",
        cv=3,
    )

    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", calibrated_clf),
        ]
    )
    return pipeline


def train_and_evaluate(
    df: Optional[pd.DataFrame] = None,
    save_path: str = MODEL_PATH,
) -> Tuple[Pipeline, Dict[str, float]]:
    """
    Trains the calibrated recovery model and reports ROC-AUC, Brier score, and accuracy.
    """
    if df is None:
        if os.path.exists(DATASET_PATH):
            df = pd.read_csv(DATASET_PATH)
        else:
            df = generate_batch(5000)

    X_raw = df[["error_code", "method", "amount_inr", "prior_failures"]]
    X = prepare_features(X_raw)
    y = df["recovered"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    y_pred_proba = pipeline.predict_proba(X_test)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)

    auc = roc_auc_score(y_test, y_pred_proba)
    acc = accuracy_score(y_test, y_pred)
    brier = brier_score_loss(y_test, y_pred_proba)

    metrics = {
        "roc_auc": round(float(auc), 4),
        "accuracy": round(float(acc), 4),
        "brier_score": round(float(brier), 4),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
    }

    print("\n==========================================")
    print(" ENHANCED CALIBRATED MODEL RESULTS")
    print("==========================================")
    print(f" Train size   : {metrics['train_samples']} records")
    print(f" Test size    : {metrics['test_samples']} records")
    print(f" ROC-AUC      : {metrics['roc_auc']:.4f}")
    print(f" Accuracy     : {metrics['accuracy']:.4f}")
    print(f" Brier Score  : {metrics['brier_score']:.4f} (Lower is better)")
    print("==========================================\n")

    joblib.dump(pipeline, save_path)
    print(f"[INFO] Enhanced model successfully saved to {save_path}")

    global _CACHED_MODEL
    _CACHED_MODEL = pipeline

    return pipeline, metrics


def get_model(model_path: str = MODEL_PATH) -> Optional[Pipeline]:
    global _CACHED_MODEL
    if _CACHED_MODEL is not None:
        return _CACHED_MODEL

    if os.path.exists(model_path):
        try:
            _CACHED_MODEL = joblib.load(model_path)
            return _CACHED_MODEL
        except Exception as e:
            logger.error("Failed to load recovery model: %s. Using Oracle fallback.", e)
            return None
    return None


def predict_batch_probabilities(
    df: pd.DataFrame,
    model: Optional[Pipeline] = None,
) -> np.ndarray:
    """Vectorized probability prediction for large batches."""
    active_model = model or get_model()
    if active_model is not None:
        try:
            X_input = prepare_features(df)
            probs = active_model.predict_proba(X_input)[:, 1]
            # Override hard declines with strict 0.0
            is_hard = df["error_code"].isin(HARD_DECLINE_CODES)
            probs[is_hard] = 0.0
            return probs
        except Exception as e:
            logger.warning("Batch ML prediction failed (%s). Falling back to Oracle.", e)

    # Fallback to Oracle mapping
    return np.array([ORACLE_PROBS.get(c, 0.20) for c in df["error_code"]])


def predict_recovery_probability(
    features: Dict[str, Any],
    model: Optional[Pipeline] = None,
) -> float:
    """
    Predicts calibrated probability of recovering payment using ML pipeline.
    Guarantees strict compliance safety and robust fallback.
    """
    error_code = features.get("error_code", "unknown")
    
    # 1. Strict Compliance Guardrail: Hard declines are NEVER predicted positive
    if error_code in HARD_DECLINE_CODES:
        return 0.0

    active_model = model or get_model()

    if active_model is not None:
        try:
            raw_df = pd.DataFrame([
                {
                    "error_code": error_code,
                    "method": features.get("method") or "card",
                    "amount_inr": float(features.get("amount_inr", 100.0)),
                    "prior_failures": int(features.get("prior_failures", 0)),
                }
            ])
            X_input = prepare_features(raw_df)
            prob = float(active_model.predict_proba(X_input)[0, 1])
            return round(prob, 4)
        except Exception as e:
            logger.warning("ML prediction failed (%s). Falling back to Oracle table.", e)

    # 2. Out-of-Distribution / Fallback
    return ORACLE_PROBS.get(error_code, 0.20)


if __name__ == "__main__":
    from simulate import generate_and_save_dataset
    generate_and_save_dataset()
    train_and_evaluate()
