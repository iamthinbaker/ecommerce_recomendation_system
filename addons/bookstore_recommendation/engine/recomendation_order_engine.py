import json
import os

import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity


class OrderRecommendationEngine:

    def preprocess(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        basket = (
            df.assign(bought=1)
            .pivot_table(
                index="order_id",
                columns="product_id",
                values="bought",
                aggfunc="max",
                fill_value=0,
            )
            .astype(np.float32)
        )
        return basket

    def train(
        self,
        data: pd.DataFrame,
    ):

        basket = self.preprocess(data)

        self.popular_products = (
            data.groupby("product_id")["order_id"].count().sort_values(ascending=False)
        )

        self.similarity_df = pd.DataFrame(
            cosine_similarity(basket.T),
            index=basket.columns,
            columns=basket.columns,
        ).where(
            ~np.eye(basket.shape[1], dtype=bool),
            other=0.0,
        )

        return self

    def save_model(self, path: str, top_k: int = 50) -> None:
        sparse_sim = {
            int(pid): {
                int(nid): round(float(score), 5)
                for nid, score in self.similarity_df[pid].nlargest(top_k).items()
                if score > 0
            }
            for pid in self.similarity_df.columns
        }
        popular = {int(k): int(v) for k, v in self.popular_products.items()}

        dir_name = os.path.dirname(path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"similarity": sparse_sim, "popular_products": popular}, f)

    @classmethod
    def load_model(cls, path: str) -> "OrderRecommendationEngine":
        with open(path) as f:
            raw = json.load(f)

        sparse_sim = {
            int(k): {int(nk): v for nk, v in neighbors.items()}
            for k, neighbors in raw["similarity"].items()
        }

        engine = cls()
        engine.similarity_df = pd.DataFrame(sparse_sim).fillna(0.0).astype(np.float32)
        engine.popular_products = (
            pd.Series({int(k): v for k, v in raw.get("popular_products", {}).items()})
            .sort_values(ascending=False)
        )
        return engine

    def predict(
        self,
        sample: pd.DataFrame,
        limit: int = 6,
    ) -> pd.Series:

        cart_ids = set(sample["product_id"].tolist())
        in_matrix = [pid for pid in cart_ids if pid in self.similarity_df.columns]

        if not in_matrix:
            return self.popular_products[
                ~self.popular_products.index.isin(cart_ids)
            ].head(limit)

        scores = (
            self.similarity_df[in_matrix]
            .sum(axis=1)
            .drop(index=list(cart_ids & set(self.similarity_df.index)))
            .nlargest(limit)
            .replace(0, np.nan)
            .dropna()
        )

        exclude = set(scores.index) | cart_ids
        scores = pd.concat(
            [
                scores,
                self.popular_products[
                    ~self.popular_products.index.isin(exclude)
                ].head(limit - len(scores)),
            ],
        ).head(limit)

        return scores
