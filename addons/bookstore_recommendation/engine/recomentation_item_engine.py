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

        features = self.preprocess(data)

        self.similarity_df = pd.DataFrame(
            cosine_similarity(features.values),
            index=data.set_index([i for i in data.columns]).index,
            columns=features.index,
        )

        return self

    def predict(
        self,
        product_tmpl_id,
        limit=6,
    ):
        if self.similarity_df is None:
            return None

        if product_tmpl_id not in self.similarity_df.index:
            return None

        scores = (
            (
                self.similarity_df[product_tmpl_id]
                .drop(product_tmpl_id)
                .nlargest(limit * 3)
                .to_frame("similarity")
            )
            .sort_values("similarity", ascending=False)
            .head(limit)
        )

        return scores
