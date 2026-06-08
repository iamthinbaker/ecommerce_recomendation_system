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

    def predict(
        self,
        sample: pd.DataFrame,
        limit: int = 6,
    ) -> pd.Series:

        cart_ids = set(sample["product_id"].tolist())
        in_matrix = [pid for pid in cart_ids if pid in self.similarity_df.columns]

        if not in_matrix:
            return self.popular_products.head(limit)

        scores = (
            self.similarity_df[in_matrix]
            .sum(axis=1)
            .drop(index=list(cart_ids & set(self.similarity_df.index)))
            .nlargest(limit)
            .replace(0, np.nan)
            .dropna()
        )

        scores = pd.concat(
            [
                scores,
                self.popular_products.drop(index=scores.index).head(
                    limit - len(scores)
                ),
            ],
        ).head(limit)

        return scores
