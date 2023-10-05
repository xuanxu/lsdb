from typing import Dict, Tuple, List

import dask.dataframe as dd
import hipscat as hc
import pandas as pd
from dask import delayed
from hipscat.catalog.catalog_info import CatalogInfo
from hipscat.pixel_math import generate_histogram, HealpixPixel
from hipscat.pixel_math.hipscat_id import healpix_to_hipscat_id, compute_hipscat_id

from lsdb.catalog.catalog import Catalog, DaskDFPixelMap
from lsdb.io.csv_io import read_csv_file_to_pandas


class DataframeCatalogLoader:
    """Loads a HiPSCat formatted Catalog from a Pandas Dataframe"""

    HISTOGRAM_ORDER = 10

    def __init__(self, path: str, threshold: int = 50, **kwargs) -> None:
        """Initializes a DataframeCatalogLoader

        Args:
            path (str): Path to a CSV file
            threshold (int): The maximum number of data points per pixel
            **kwargs: Arguments to pass to the creation of the catalog info
        """
        self.path = hc.io.get_file_pointer_from_path(path)
        self.threshold = threshold
        self.catalog_info = CatalogInfo(**kwargs)

    def load_catalog(self) -> Catalog:
        """Load a catalog from a pandas Dataframe, in CSV format

        Returns:
            Catalog object with data from the source given at loader initialization
        """
        # Read data points from catalog CSV
        df = read_csv_file_to_pandas(self.path)
        # Compute hipscat indices and use them as Dataframe index
        self._set_hipscat_index(df)
        # Compute pixel mapping
        pixel_map = self._get_pixel_map(df)
        # Load dask dataframe and get Healpix Pixel to partition mapping
        ddf, ddf_pixel_map = self._load_dask_df_and_map(df, pixel_map)
        # Init Hipscat Catalog object
        hc_structure = self._init_hipscat_catalog(list(pixel_map.keys()))
        # Init LSDB Catalog
        return Catalog(ddf, ddf_pixel_map, hc_structure)

    def _set_hipscat_index(self, df: pd.DataFrame):
        """Generates the hipscat indices for each data point
        and assigns the hipscat_index column as the dataframe index.

        Args:
            df (pd.Dataframe): The catalog Pandas Dataframe
        """
        # For each data point, calculate HiPSCat index
        # and add index as column of the dataframe
        df["hipscat_index"] = compute_hipscat_id(
            ra_values=df[self.catalog_info.ra_column],
            dec_values=df[self.catalog_info.dec_column],
        )
        # Update index of the dataframe
        df.set_index("hipscat_index", inplace=True)

    def _get_pixel_map(self, df: pd.DataFrame) -> Dict[HealpixPixel, Tuple[int, List[int]]]:
        """Compute object histogram and generate the mapping between
        Healpix pixels and the respective original pixel information

        Args:
            df (pd.Dataframe): The catalog Pandas Dataframe

        Returns:
            A dictionary mapping each Healpix pixel to the respective
            information tuple. The first value of the tuple is the number
            of objects in the Healpix pixel, the second is the list of pixels
        """
        # Generate object histogram (for each Healpix pixel, have the number
        # of objects it contains)
        raw_histogram = generate_histogram(
            df,
            highest_order=self.HISTOGRAM_ORDER,
            ra_column=self.catalog_info.ra_column,
            dec_column=self.catalog_info.dec_column,
        )
        # Compute pixel map (Dict[HealpixPixel, tuple])
        # {OnPk : (n_points, [pix1,pix2])}
        # : For each Healpix pixel of order k (being k the order used for
        # generating the histogram), get the number of objects in it and
        # the original pixels containing them
        return hc.pixel_math.compute_pixel_map(
            raw_histogram, highest_order=self.HISTOGRAM_ORDER, threshold=self.threshold
        )

    def _load_dask_df_and_map(
        self, df: pd.DataFrame, pixel_map: Dict[HealpixPixel, Tuple]
    ) -> Tuple[dd.DataFrame, DaskDFPixelMap]:
        """Load Dask DataFrame from Healpix pixel Dataframes and
        generate a mapping of Healpix pixels to Healpix Dataframes

        Args:
            df (pd.Dataframe): The catalog Pandas Dataframe
            pixel_map (Dict[HealpixPixel, Tuple]): The mapping between
                HealPix pixels and respective data information

        Returns:
            Tuple containing the Dask Dataframe and the mapping of
            Healpix pixels to the respective Pandas Dataframes
        """
        # For each destination Healpix pixel, get the list of Dataframes
        # (i.e., the data points belonging to that pixel)
        # [OnPk,...] -> [df(n,k)...]
        pixel_dfs: List[pd.DataFrame] = []

        # Map Healpix pixel to the respective Pandas Dataframe index
        # Dict[HP,int], where int is the Pandas DataFrame index
        ddf_pixel_map: Dict[HealpixPixel, int] = {}

        # Calculate Hipscat indices for the current Healpix pixel
        for hp_pixel_index, hp_pixel_info in enumerate(pixel_map.items()):
            hp_pixel, (_, pixels) = hp_pixel_info
            pixel_dfs.append(self._get_dataframe_for_healpix(df, pixels))
            ddf_pixel_map[hp_pixel] = hp_pixel_index

        # Create a Dask DataFrame from the list of delayed objects
        delayed_dfs = [delayed(pd.DataFrame)(df) for df in pixel_dfs]
        ddf = dd.from_delayed(delayed_dfs)

        return ddf, ddf_pixel_map

    def _init_hipscat_catalog(self, pixels: List[HealpixPixel]) -> hc.catalog.Catalog:
        """Initializes the Hipscat Catalog object

        Args:
            pixels (List[HealpixPixel]): The list of Healpix pixels

        Returns:
            The Hipscat catalog object
        """
        return hc.catalog.Catalog(self.catalog_info, pixels)

    def _get_dataframe_for_healpix(self, df: pd.DataFrame, pixels: List[int]) -> pd.DataFrame:
        """Computes the Pandas Dataframe containing the data points
        for a certain HealPix pixel.

        Args:
            df (pd.Dataframe): The catalog Pandas Dataframe
            pixels (List[int]): The indices of the pixels inside the Healpix pixel.

        Returns:
            The Pandas Dataframe containing the data points for the Healpix pixel.
        """
        left_bound = healpix_to_hipscat_id(self.HISTOGRAM_ORDER, pixels[0])
        right_bound = healpix_to_hipscat_id(self.HISTOGRAM_ORDER, pixels[-1] + 1)
        return df.loc[(df.index >= left_bound) & (df.index < right_bound)]
