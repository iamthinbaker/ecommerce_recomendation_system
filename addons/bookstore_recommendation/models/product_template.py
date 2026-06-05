from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    book_author = fields.Char(string='Author', index=True)
    book_isbn = fields.Char(string='ISBN', index=True)
    book_genre_id = fields.Many2one(
        comodel_name='book.genre',
        string='Genre',
        ondelete='set null',
        index=True,
    )
    book_sub_genre_id = fields.Many2one(
        comodel_name='book.genre',
        string='Sub-genre',
        ondelete='set null',
        index=True,
    )
    book_pages = fields.Integer(string='Pages')
    book_publisher = fields.Char(string='Publisher')
    book_year = fields.Integer(string='Publication Year')
    book_promoted = fields.Boolean(string='Promoción', default=False)
    is_book = fields.Boolean(
        string='Is a Book',
        compute='_compute_is_book',
        store=True,
    )

    @api.depends('categ_id')
    def _compute_is_book(self):
        book_categ = self.env.ref(
            'bookstore_recommendation.product_category_books',
            raise_if_not_found=False,
        )
        for product in self:
            product.is_book = bool(
                book_categ and product.categ_id == book_categ
            )
