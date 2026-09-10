"""split products into spus and skus tables

Revision ID: 731546794d12
Revises: 330c6bbf4c9e
Create Date: 2026-09-09 15:05:09.495692

将旧 products 单表拆分为 spus（主产品）+ skus（具体规格）两张表。
数据迁移规则：
- 旧 is_parent=true 的记录 → spus 表（父体/主产品，无 ASIN、不可售）
- 旧 is_parent=false 且 variation_parent 非空的记录 → skus 表（子体/规格，spu_id 指向父体）
- 旧 is_parent=false 且 variation_parent 为空的「独立产品」记录 → 拆成 1 个 SPU + 1 个 SKU
  （SPU 承载公共属性，SKU 承载价格/库存/ASIN，规格值为空）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '731546794d12'
down_revision: Union[str, Sequence[str], None] = '330c6bbf4c9e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: products → spus + skus"""
    # 1) 创建 spus 表
    op.create_table(
        'spus',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('brand', sa.String(length=128), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('sub_category', sa.String(length=64), nullable=False),
        sa.Column('spu_theme', sa.String(length=32), nullable=True),
        sa.Column('keywords', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('selling_points', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('main_image', sa.Text(), nullable=False),
        sa.Column('images', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('spu_common', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('shop_id', sa.String(length=64), nullable=False),
        sa.Column('tags', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('groups', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.String(length=64), nullable=False),
        sa.Column('updated_at', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id', name='spus_pkey'),
    )

    # 2) 创建 skus 表
    op.create_table(
        'skus',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('spu_id', sa.String(length=64), nullable=False),
        sa.Column('spec_value', sa.String(length=64), nullable=True),
        sa.Column('asin', sa.String(length=32), nullable=False),
        sa.Column('sku_code', sa.String(length=64), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('cost', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=8), nullable=False),
        sa.Column('site', sa.String(length=64), nullable=True),
        sa.Column('fba_stock', sa.Integer(), nullable=False),
        sa.Column('fbm_stock', sa.Integer(), nullable=False),
        sa.Column('fulfillment_type', sa.String(length=8), nullable=False),
        sa.Column('bsr', sa.Integer(), nullable=True),
        sa.Column('rating', sa.Float(), nullable=False),
        sa.Column('review_count', sa.Integer(), nullable=False),
        sa.Column('daily_sales_avg', sa.Float(), nullable=False),
        sa.Column('roi', sa.Float(), nullable=False),
        sa.Column('margin', sa.Float(), nullable=False),
        sa.Column('listing_status', sa.String(length=16), nullable=False),
        sa.Column('generated_title', sa.Text(), nullable=True),
        sa.Column('generated_bullets', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('generated_a_plus', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('seo_score', sa.Integer(), nullable=True),
        sa.Column('generated_at', sa.String(length=64), nullable=True),
        sa.Column('listing_version', sa.Integer(), nullable=False),
        sa.Column('listing_history', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('has_a_plus', sa.Boolean(), nullable=False),
        sa.Column('has_video', sa.Boolean(), nullable=False),
        sa.Column('rating_breakdown', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('tags', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.String(length=64), nullable=False),
        sa.Column('updated_at', sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(['spu_id'], ['spus.id'], name='skus_spu_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='skus_pkey'),
    )
    op.create_index('ix_skus_spu_id', 'skus', ['spu_id'], unique=False)
    op.create_index('ix_skus_asin', 'skus', ['asin'], unique=False)

    # 3) 数据迁移：旧父体（is_parent=true）→ spus
    op.execute("""
        INSERT INTO spus (id, title, brand, category, sub_category, spu_theme,
                          keywords, selling_points, description, main_image, images,
                          spu_common, shop_id, tags, notes, status, groups, created_at, updated_at)
        SELECT id, title, brand, category, sub_category, variation_theme,
               keywords, selling_points, description, main_image, images,
               parent_content, shop_id, tags, notes, status, groups, created_at, updated_at
        FROM products WHERE is_parent = true
    """)

    # 4) 数据迁移：旧子体（variation_parent 非空）→ skus
    op.execute("""
        INSERT INTO skus (id, spu_id, spec_value, asin, sku_code, price, cost, currency, site,
                          fba_stock, fbm_stock, fulfillment_type, bsr, rating, review_count,
                          daily_sales_avg, roi, margin, listing_status,
                          generated_title, generated_bullets, generated_a_plus, seo_score,
                          generated_at, listing_version, listing_history,
                          has_a_plus, has_video, rating_breakdown, tags, notes, status, created_at, updated_at)
        SELECT id, variation_parent, variation_value, asin, sku, price, cost, currency, site,
               fba_stock, fbm_stock, fulfillment_type, bsr, rating, review_count,
               daily_sales_avg, roi, margin, listing_status,
               generated_title, generated_bullets, generated_a_plus, seo_score,
               generated_at, listing_version, listing_history,
               has_a_plus, has_video, rating_breakdown, tags, notes, status, created_at, updated_at
        FROM products WHERE is_parent = false AND variation_parent IS NOT NULL
    """)

    # 5) 数据迁移：旧独立产品（is_parent=false 且无 variation_parent）→ 拆成 1 SPU + 1 SKU
    op.execute("""
        INSERT INTO spus (id, title, brand, category, sub_category, spu_theme,
                          keywords, selling_points, description, main_image, images,
                          spu_common, shop_id, tags, notes, status, groups, created_at, updated_at)
        SELECT id, title, brand, category, sub_category, variation_theme,
               keywords, selling_points, description, main_image, images,
               parent_content, shop_id, tags, notes, status, groups, created_at, updated_at
        FROM products WHERE is_parent = false AND (variation_parent IS NULL OR variation_parent = '')
    """)
    op.execute("""
        INSERT INTO skus (id, spu_id, spec_value, asin, sku_code, price, cost, currency, site,
                          fba_stock, fbm_stock, fulfillment_type, bsr, rating, review_count,
                          daily_sales_avg, roi, margin, listing_status,
                          generated_title, generated_bullets, generated_a_plus, seo_score,
                          generated_at, listing_version, listing_history,
                          has_a_plus, has_video, rating_breakdown, tags, notes, status, created_at, updated_at)
        SELECT id || '-sku-0', id, variation_value, asin, sku, price, cost, currency, site,
               fba_stock, fbm_stock, fulfillment_type, bsr, rating, review_count,
               daily_sales_avg, roi, margin, listing_status,
               generated_title, generated_bullets, generated_a_plus, seo_score,
               generated_at, listing_version, listing_history,
               has_a_plus, has_video, rating_breakdown, tags, notes, status, created_at, updated_at
        FROM products WHERE is_parent = false AND (variation_parent IS NULL OR variation_parent = '')
    """)

    # 6) drop 旧 products 表
    op.drop_index('ix_products_asin', table_name='products')
    op.drop_table('products')


def downgrade() -> None:
    """Downgrade schema: spus + skus → products（重建旧单表，数据回填）"""
    op.create_table(
        'products',
        sa.Column('id', sa.String(length=64), autoincrement=False, nullable=False),
        sa.Column('asin', sa.String(length=32), autoincrement=False, nullable=False),
        sa.Column('sku', sa.String(length=64), autoincrement=False, nullable=False),
        sa.Column('title', sa.String(length=500), autoincrement=False, nullable=False),
        sa.Column('brand', sa.String(length=128), autoincrement=False, nullable=False),
        sa.Column('category', sa.String(length=32), autoincrement=False, nullable=False),
        sa.Column('sub_category', sa.String(length=64), autoincrement=False, nullable=False),
        sa.Column('price', sa.Float(), autoincrement=False, nullable=False),
        sa.Column('cost', sa.Float(), autoincrement=False, nullable=False),
        sa.Column('cost_price', sa.Float(), autoincrement=False, nullable=True),
        sa.Column('selling_price', sa.Float(), autoincrement=False, nullable=True),
        sa.Column('currency', sa.String(length=8), autoincrement=False, nullable=False),
        sa.Column('site', sa.String(length=64), autoincrement=False, nullable=True),
        sa.Column('keywords', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('competitor_asins', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('selling_points', sa.Text(), autoincrement=False, nullable=True),
        sa.Column('description', sa.Text(), autoincrement=False, nullable=True),
        sa.Column('listing_status', sa.String(length=16), autoincrement=False, nullable=False),
        sa.Column('bsr', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('rating', sa.Float(), autoincrement=False, nullable=False),
        sa.Column('review_count', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('generated_title', sa.Text(), autoincrement=False, nullable=True),
        sa.Column('generated_bullets', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('generated_a_plus', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('seo_score', sa.Integer(), autoincrement=False, nullable=True),
        sa.Column('generated_at', sa.String(length=64), autoincrement=False, nullable=True),
        sa.Column('listing_version', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('listing_history', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('main_image', sa.Text(), autoincrement=False, nullable=False),
        sa.Column('images', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('has_a_plus', sa.Boolean(), autoincrement=False, nullable=False),
        sa.Column('has_video', sa.Boolean(), autoincrement=False, nullable=False),
        sa.Column('rating_breakdown', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('variation_parent', sa.String(length=64), autoincrement=False, nullable=True),
        sa.Column('variation_theme', sa.String(length=32), autoincrement=False, nullable=True),
        sa.Column('variation_value', sa.String(length=64), autoincrement=False, nullable=True),
        sa.Column('is_parent', sa.Boolean(), server_default=sa.text('false'), autoincrement=False, nullable=False),
        sa.Column('variations', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('parent_content', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('fba_stock', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('fbm_stock', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('fulfillment_type', sa.String(length=8), autoincrement=False, nullable=False),
        sa.Column('daily_sales_avg', sa.Float(), autoincrement=False, nullable=False),
        sa.Column('roi', sa.Float(), autoincrement=False, nullable=False),
        sa.Column('margin', sa.Float(), autoincrement=False, nullable=False),
        sa.Column('shop_id', sa.String(length=64), autoincrement=False, nullable=False),
        sa.Column('tags', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('notes', sa.Text(), autoincrement=False, nullable=False),
        sa.Column('status', sa.String(length=16), autoincrement=False, nullable=False),
        sa.Column('groups', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.Column('created_at', sa.String(length=64), autoincrement=False, nullable=False),
        sa.Column('updated_at', sa.String(length=64), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint('id', name='products_pkey'),
    )
    op.create_index('ix_products_asin', 'products', ['asin'], unique=False)

    # 回填：spus → products（父体）
    op.execute("""
        INSERT INTO products (id, asin, sku, title, brand, category, sub_category, price, cost,
                              currency, keywords, selling_points, description, listing_status,
                              main_image, images, variation_parent, variation_theme, variation_value,
                              is_parent, variations, parent_content, fba_stock, fbm_stock,
                              fulfillment_type, daily_sales_avg, roi, margin, shop_id, tags, notes,
                              status, groups, created_at, updated_at)
        SELECT id, '', 'SKU-PARENT-' || id, title, brand, category, sub_category, 0, 0,
               'USD', keywords, selling_points, description, 'draft',
               main_image, images, NULL, spu_theme, NULL,
               true, '[]', spu_common, 0, 0,
               'FBA', 0, 0, 0, shop_id, tags, notes, status, groups, created_at, updated_at
        FROM spus
    """)
    # 回填：skus → products（子体/独立产品）
    op.execute("""
        INSERT INTO products (id, asin, sku, title, brand, category, sub_category, price, cost,
                              currency, keywords, selling_points, description, listing_status,
                              bsr, rating, review_count, generated_title, generated_bullets,
                              generated_a_plus, seo_score, generated_at, listing_version,
                              listing_history, main_image, images, has_a_plus, has_video,
                              rating_breakdown, variation_parent, variation_theme, variation_value,
                              is_parent, variations, parent_content, fba_stock, fbm_stock,
                              fulfillment_type, daily_sales_avg, roi, margin, shop_id, tags, notes,
                              status, groups, created_at, updated_at)
        SELECT s.id, s.asin, s.sku_code, sp.title, sp.brand, sp.category, sp.sub_category,
               s.price, s.cost, s.currency, sp.keywords, sp.selling_points, sp.description,
               s.listing_status, s.bsr, s.rating, s.review_count, s.generated_title,
               s.generated_bullets, s.generated_a_plus, s.seo_score, s.generated_at,
               s.listing_version, s.listing_history, sp.main_image, sp.images, s.has_a_plus,
               s.has_video, s.rating_breakdown, s.spu_id, sp.spu_theme, s.spec_value,
               false, '[]', sp.spu_common, s.fba_stock, s.fbm_stock, s.fulfillment_type,
               s.daily_sales_avg, s.roi, s.margin, sp.shop_id, s.tags, s.notes, s.status,
               sp.groups, s.created_at, s.updated_at
        FROM skus s LEFT JOIN spus sp ON s.spu_id = sp.id
    """)

    op.drop_index('ix_skus_asin', table_name='skus')
    op.drop_index('ix_skus_spu_id', table_name='skus')
    op.drop_table('skus')
    op.drop_table('spus')
