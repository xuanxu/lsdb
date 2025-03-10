import dask.dataframe as dd
import pandas as pd
from hipscat.pixel_math import HealpixPixel


def test_catalog_pixels_equals_hc_catalog_pixels(small_sky_order1_catalog, small_sky_order1_hipscat_catalog):
    assert (
        small_sky_order1_catalog.get_healpix_pixels() == small_sky_order1_hipscat_catalog.get_healpix_pixels()
    )


def test_catalog_repr_equals_ddf_repr(small_sky_order1_catalog):
    assert repr(small_sky_order1_catalog) == repr(small_sky_order1_catalog._ddf)


def test_catalog_html_repr_equals_ddf_html_repr(small_sky_order1_catalog):
    assert small_sky_order1_catalog._repr_html_() == small_sky_order1_catalog._ddf._repr_html_()


def test_catalog_compute_equals_ddf_compute(small_sky_order1_catalog):
    pd.testing.assert_frame_equal(small_sky_order1_catalog.compute(), small_sky_order1_catalog._ddf.compute())


def test_get_catalog_partition_gets_correct_partition(small_sky_order1_catalog):
    for healpix_pixel in small_sky_order1_catalog.get_healpix_pixels():
        hp_order = healpix_pixel.order
        hp_pixel = healpix_pixel.pixel
        partition = small_sky_order1_catalog.get_partition(hp_order, hp_pixel)
        pixel = HealpixPixel(order=hp_order, pixel=hp_pixel)
        partition_index = small_sky_order1_catalog._ddf_pixel_map[pixel]
        ddf_partition = small_sky_order1_catalog._ddf.partitions[partition_index]
        dd.utils.assert_eq(partition, ddf_partition)
