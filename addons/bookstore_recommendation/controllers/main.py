import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class BookstoreHome(http.Controller):

    @http.route("/", type="http", auth="public", website=True, sitemap=True)
    def bookstore_home(self, search="", **kw):
        Genre = request.env["book.genre"].sudo()
        Product = request.env["product.template"].sudo()

        top_genres = Genre.search(
            [
                ("parent_id", "=", False),
                ("website_published", "=", True),
            ]
        )

        genre_sections = []
        for genre in top_genres:
            all_genre_ids = genre._get_all_child_ids()
            books = Product.search(
                [
                    ("book_genre_id", "in", all_genre_ids),
                    ("website_published", "=", True),
                ],
                limit=6,
            )
            genre_sections.append(
                {
                    "genre": genre,
                    "books": books,
                }
            )

        return request.render(
            "bookstore_recommendation.bookstore_home",
            {
                "genre_sections": genre_sections,
                "top_genres": top_genres,
                "search_value": search,
            },
        )


class BookstoreRecommendationController(http.Controller):

    @http.route(
        "/bookstore/recommendations/similar/<int:product_id>",
        type="jsonrpc",
        auth="public",
        website=True,
        readonly=True,
        methods=["POST"],
    )
    def similar_products(self, product_id, **kwargs):
        engine = request.env["recommendation.engine.item"].sudo()
        products = engine.get_similar_products(product_id, limit=5)
        return [
            {
                "id": p.id,
                "name": p.name,
                "url": p.website_url,
                "price": p.list_price,
                "image_url": f"/web/image/product.template/{p.id}/image_128",
                "author": p.book_author or "",
            }
            for p in products
        ]

    @http.route(
        "/bookstore/recommendations/user/<int:order_id>",
        type="jsonrpc",
        auth="public",
        website=True,
        readonly=True,
        methods=["POST"],
    )
    def user_recommendations(self, order_id, **kwargs):
        order = request.env["sale.order"].sudo().browse(order_id)
        if not order.exists():
            return []

        partner_id = order.partner_id.id
        engine = request.env["recommendation.engine.user"].sudo()
        products = engine.get_user_recommendations(partner_id, limit=3)
        return [
            {
                "id": p.id,
                "name": p.name,
                "url": p.website_url,
                "price": p.list_price,
                "image_url": f"/web/image/product.template/{p.id}/image_128",
                "author": p.book_author or "",
            }
            for p in products
        ]
