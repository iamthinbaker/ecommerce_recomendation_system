import os
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder
from sklearn.metrics.pairwise import cosine_similarity


class ItemRecommendationEngine:

    def preprocess(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        pipeline = ColumnTransformer(
            [
                (
                    "cat",
                    OneHotEncoder(
                        sparse_output=False,
                        handle_unknown="ignore",
                    ),
                    df.select_dtypes(
                        include=["str", "object", "category"],
                    ).columns.tolist(),
                ),
                (
                    "num",
                    MinMaxScaler(),
                    df.select_dtypes(
                        include="number",
                    ).columns.tolist(),
                ),
            ]
        )

        return pd.DataFrame(
            pipeline.fit_transform(df),
            index=df.index,
        )

    def train(
        self,
        data: pd.DataFrame,
    ):
        features = self.preprocess(data.drop(columns="id"))
        product_ids = data["id"].values

        sim = pd.DataFrame(
            cosine_similarity(features.values),
            index=product_ids,
            columns=product_ids,
        )
        self.similarity_df = sim

        return self

    def predict(
        self,
        sample: pd.DataFrame,
        limit=6,
    ):
        if self.similarity_df is None:
            return None

        product_id = sample["id"].item()

        if product_id not in self.similarity_df.index:
            return None

        scores = (
            self.similarity_df[product_id]
            .drop(product_id)
            .nlargest(limit)
            .to_frame("similarity")
        )

        return scores

    def save_model(self, path: str) -> None:

        dir_name = os.path.dirname(path)

        if dir_name:
            os.makedirs(
                dir_name,
                exist_ok=True,
            )

        self.similarity_df.to_json(
            path,
            orient="records",
            indent=4,
        )

    @classmethod
    def load_model(
        cls,
        path: str,
    ) -> "ItemRecommendationEngine":
        df = pd.read_json(path, orient="records")
        df.columns = df.columns.astype(int)
        df.index = df.columns  # restore product IDs as row index
        engine = cls()
        engine.similarity_df = df
        return engine
