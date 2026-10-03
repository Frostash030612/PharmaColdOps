"""Shared, unfitted preprocessing for deployment and independent experiments."""
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .contracts import FEATURES, CAUSE_CATEGORICAL, CAUSE_NUMERIC


def make_pipeline(task, estimator, features=None):
    features = FEATURES[task] if features is None else list(features)
    if not features or not set(features) <= set(FEATURES[task]):
        raise ValueError("only declared M4 features may enter training")
    numeric = features if task == "risk" else [k for k in features if k in CAUSE_NUMERIC]
    categories = [] if task == "risk" else [k for k in features if k in CAUSE_CATEGORICAL]
    prepare = ColumnTransformer([
        ("numeric", Pipeline([("fill", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric),
        *([("category", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categories)] if categories else []),
    ])
    return Pipeline([("prepare", prepare), ("classifier", clone(estimator))])
