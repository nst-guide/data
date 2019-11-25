import os
import re
from datetime import datetime
from zipfile import ZipFile

import pandas as pd
from dotenv import load_dotenv

from .base import DataSource


class PCTWaterReport(DataSource):
    def __init__(self):
        super(PCTWaterReport, self).__init__()

        load_dotenv()
        self.google_api_key = os.getenv('GOOGLE_SHEETS_API_KEY')
        assert self.google_api_key is not None, 'Google API Key missing'

        self.raw_dir = self.data_dir / 'raw' / 'pctwater'

    def download(self, overwrite=False):
        """Download PCT Water report spreadsheets

        For now, since I can't get the Google Drive API to work, you have to
        download the folder manually from Google Drive. If you right click on
        the folder, you can download the entire archive at once.

        Put the downloaded ZIP file at data/raw/pctwater/pctwater.zip
        """
        pass

    def import_files(self):
        """Import water reports into a single DataFrame
        """
        z = ZipFile(self.raw_dir / 'pctwater.zip')
        names = z.namelist()
        # Remove snow report files
        names = sorted([x for x in names if 'snow' not in x.lower()])

        date_re = r'(20\d{2}-[0-3]\d-[0-3]\d)( [0-2]\d_[0-6]\d_[0-6]\d)?'
        dfs = []
        for n in names:
            date_match = re.search(date_re, n)
            if date_match:
                if date_match.group(1) == '2011-30-12':
                    fmt = '%Y-%d-%m'
                else:
                    fmt = '%Y-%m-%d'
                file_date = datetime.strptime(date_match.group(1), fmt)
            else:
                file_date = datetime.now()

            # Read all sheets of Excel workbook into list
            _dfs = pd.read_excel(z.open(n), header=None, sheet_name=None)
            for df in _dfs.values():
                df = self._clean_dataframe(df)
                if df is not None:
                    dfs.append([file_date, df])

        single_df = pd.concat([x[1] for x in dfs], sort=False)
        single_df.to_csv(self.raw_dir / 'single.csv', index=False)

    def _clean_dataframe(self, df):
        # TODO: merge with waypoint data to get stable lat/lon positions

        # In 2017, a sheet in the workbook is for snow reports
        if df.iloc[0, 0] == 'Pacific Crest Trail Snow & Ford Report':
            return None

        df = self._assemble_df_with_named_columns(df)
        df = self._resolve_df_names(df)

        # column 'map' should meet the map regex
        # Keep only rows that meet regex
        map_col_regex = re.compile(r'^[A-Z][0-9]{,2}$')
        df = df[df['map'].str.match(map_col_regex).fillna(False)]

        df = self._split_report_rows(df)
        return df

    def _resolve_df_names(self, df):
        """
        Columns should be
        [map, mile, waypoint, location, report, date, reported by, posted]
        """
        # To lower case
        df = df.rename(mapper=lambda x: x.lower(), axis='columns')

        # Rename any necessary columns
        rename_dict = {
            '2015 mile\nhalfmile app': 'mile_old',
            'old mile*': 'mile_old',
            'miles (nobo)': 'mile',
            'report ("-" means no report)': 'report'
        }
        df = df.rename(columns=rename_dict)

        should_be = [
            'map', 'mile', 'mile_old', 'waypoint', 'location', 'report', 'date',
            'reported by', 'posted'
        ]
        invalid_cols = set(df.columns).difference(should_be)
        if invalid_cols:
            raise ValueError(f'extraneous column {invalid_cols}')

        return df

    def _split_report_rows(self, df):
        """Split multiple reports into individual rows
        """
        # Remove empty report rows
        df = df[df['report'].fillna('').str.len() > 0]

        # Sometimes there's no data in the excel sheet, i.e. at the beginning of
        # the season
        if len(df) == 0:
            return None

        # Create new columns
        idx_cols = df.columns.difference(['report'])
        new_cols_df = pd.DataFrame(df['report'].str.split('\n').tolist())
        # name columns as report0, report1, report2
        new_cols_df = new_cols_df.rename(
            mapper=lambda col: f'report{col}', axis=1)

        # Append these new columns to full df
        assert len(df) == len(new_cols_df)
        df = pd.concat(
            [df.reset_index(drop=True),
             new_cols_df.reset_index(drop=True)],
            axis=1)
        assert len(df) == len(new_cols_df)

        # Remove original 'report' column
        df = df.drop('report', axis=1)

        # Melt from wide to long
        # Bug prevents working when date is a datetime dtype
        df['date'] = df['date'].astype(str)
        reshaped = pd.wide_to_long(
            df, stubnames='report', i=idx_cols, j='report_num')
        reshaped = reshaped.reset_index()
        # remove new j column
        reshaped = reshaped.drop('report_num', axis=1)
        # Remove extra rows created from melt
        reshaped = reshaped[~reshaped['report'].isna()]

        return reshaped

    def _assemble_df_with_named_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create DataFrame with named columns

        Column order changes across time in the water reports. Instead of
        relying solely on order, first remove the pre-header lines, attach
        labels, and reassemble as DataFrame.
        """
        column_names = None
        past_header = False
        rows = []
        for row in df.itertuples(index=False, name='Pandas'):
            # print(row)
            if str(row[0]).lower() == 'map':
                column_names = row
                past_header = True
                continue

            if not past_header:
                continue

            rows.append(row)

        if column_names is None:
            raise ValueError('column names not found')

        return pd.DataFrame.from_records(rows, columns=column_names)

    def clean(self):
        df = pd.read_csv(self.raw_dir / 'single.csv')

        # While index exists in saved file
        if df.columns[0] == 'Unnamed: 0':
            df = df.drop('Unnamed: 0', axis=1)

        df = self._clean_report_column(df)

    def _clean_report_column(self, df):
        """
        Clean report string: extract the date and trail name, and remove invalid
        rows.
        """
        # Remove rows where there's no report
        df = df[~df['report'].isna()]
        df = df[~df['report'].str.match(r'^\s*-+\s*$')]

        # For many rows, `report` has its own date from being reshaped. However
        # there are also many rows (~70,000) where there's no date in the report
        # column. For those I'll just use the date from the `date` column.
        report_date_re = r'^\s*(\d{,2}[/-]\d{,2}[/-]\d{,2})'
        df['contains_date'] = df['report'].str.match(report_date_re)

        # Split into two dfs, then later join them. For the rows where report
        # contains a date, it generally also contains a trail name, and those
        # should be removed to create "clean" report data
        df_date = df.loc[df['contains_date']].copy()

        # Create date from report string
        df_date.loc[:, 'new_date'] = pd.to_datetime(
            df_date['report'].str.extract(report_date_re).iloc[:, 0],
            errors='coerce')
        # Fill in date for missing values from `date` column
        s = df_date.loc[df_date['new_date'].isna(), 'date']
        df_date.loc[df_date['new_date'].isna(), 'new_date'] = s
        # Drop `date` column and rename `new_date` to `date`
        df_date = df_date.drop('date', axis=1)
        df_date = df_date.rename(columns={'new_date': 'date'})

        # Extract trail name from report string
        trail_name_re = r'^[^\(]*\(([^\)]*)\)'
        df_date.loc[:, 'trail_name'] = df_date['report'].str.extract(
            trail_name_re).iloc[:, 0]
        # Fill in `trail_name` for missing values from `reported_by` column
        df_date.loc[df_date['trail_name'].isna(), 'trail_name'] = df_date.loc[
            df_date['trail_name'].isna(), 'reported by']
        df_date = df_date.drop('reported by', axis=1)
        df_date = df_date.rename(columns={'trail_name': 'reported by'})

        # Split report on either : or )
        # This removes the date and trail name from the report response
        # Note that if neither : nor ) are found, this returns the original str
        split_re = r'[:\)]'
        s = df_date['report'].str.split(split_re)
        df_date.loc[:, 'report'] = s.apply(
            lambda row: ' '.join(row[1:]).strip())

        # Now concatenate these two halves
        df_nodate = df.loc[~df['contains_date']].copy()
        df = pd.concat([df_date, df_nodate], axis=0, sort=False)
        df = df.drop(['contains_date', 'posted'], axis=1)

        # Drop rows with missing date value
        # NOTE: could do this just for df_nodate before concat
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.loc[df['date'].notna()]

        # Take only first line of location string
        df = df.loc[df['location'].notna()]
        s = df['location'].str.split('\n')
        df['location'] = s.apply(lambda row: row[0])

        # Only keep water waypoints
        df = df.loc[df['waypoint'].str[0] == 'W']

        # Drop duplicate rows
        # Duplicate rows can come from a few different ways here, but the
        # simplest is that in recent years a spreadsheet has been saved _weekly_
        # and some water sources get updates less frequently, so someone's
        # comments might show up in multiple files
        # Note that this brings down the row count from 134790 to 13567
        df = df.drop_duplicates(keep='first')

        return df

    # def _assign_geometry(self, df):
    #     """
    #     Attempt to assign latitude and longitude to every row in water report
    #
    #     For now, only keep PCT water rows with a non-missing waypoint identifier
    #     """
    #
    #     from fuzzywuzzy import fuzz
    #     from fuzzywuzzy import process
    #
    #
    #     hm = Halfmile()
    #     waypoints = pd.concat([df for section_name, df in hm.wpt_iter()])
    #     waypoint_names = waypoints['name'].unique()
    #
    #     # For now require waypoint to be nonmissing
    #     df = df.loc[df['waypoint'].notna()]
    #
    #     # Split into calendar years from 2015-2019
    #     df_dict = {}
    #     years = range(2015, 2020)
    #     for year in years:
    #         df_dict[year] = df.loc[df['date'].dt.year == year]
    #
    #     # Within each year, get unique waypoints
    #     wpts_year = {}
    #     wpt_cols = ['location', 'map', 'mile', 'waypoint']
    #     for year, dfi in df_dict.items():
    #         wpts_year[year] = dfi.drop_duplicates(subset=['waypoint'])[wpt_cols]
    #
    #     # Now try to match those unique waypoints across years
    #     # For now, just do an inner merge from 2015 to 2019
    #     # First, get all waypoint ids that exist in all years
    #     all_wpt_ids = [set(df['waypoint'].values) for df in wpts_year.values()]
    #     wpt_int = set.intersection(*all_wpt_ids)
    #
    #     for this_year, next_year in zip(years, years[1:]):
    #         wpt_this = wpts_year[this_year]
    #         wpt_next = wpts_year[next_year]
    #
    #     dfs = [v for k, v in wpts_year.items() if k in range(2016, 2020)]
    #     wpts_year[2015].join(dfs, on='waypoint')
    #     this_year = 2016
    #     next_year = 2017
    #     for this_year, next_year in zip(years, years[1:]):
    #         wpt_this = wpts_year[this_year]
    #         wpt_next = wpts_year[next_year]
    #
    #         self._merge_waypoints_across_years(earlier=wpt_this, later=wpt_next)
    #
    #
    #     def _merge_waypoints_across_years(self, earlier, later):
    #         """Merge waypoints across years
    #
    #         Waypoints identifiers can shift across years. Try to deal with this.
    #         For now, it just does an inner merge, but could/should be improved
    #         using fuzzy matching in the future.
    #         """
    #
    #         later.sort_values('waypoint')
    #         earlier.sort_values('waypoint')
    #         len(later)
    #         len(earlier)
    #         len(merged)
    #         merged = pd.merge(earlier, later, on='waypoint', how='outer', suffixes=('', '_y'), indicator=True)
    #         merged[merged['_merge'] != 'both'].sort_values('waypoint')
    #         merged.sort_values(['waypoint'])
    #         merged = pd.merge(earlier, later, on='waypoint', how='inner', suffixes=('', '_y'))
    #         (merged['mile'] == merged['mile_y']).mean()
    #         return merged[['location', 'map','mile', 'waypoint']]
    #
    #         wpt_this = wpt_this.sort_values(['map', 'mile'])
    #         wpt_next = wpt_next.sort_values(['map', 'mile'])
    #
    #         # Find which of this year's waypoints is not in next years
    #         changed = set(wpt_this['waypoint']).difference(wpt_next['waypoint'])
    #         it = iter(changed)
    #         wpt_id = next(it)
    #         RATIO_THRESHOLD = 90
    #         changed_df = wpt_this[wpt_this['waypoint'].isin(changed)]
    #
    #         for wpt_id in changed:
    #             row = wpt_this[wpt_this['waypoint'] == wpt_id]
    #
    #             s1 = row['location'].values[0]
    #             ratios = [fuzz.partial_ratio(s1, s2) for s2 in wpt_next['location']]
    #             ratios = [fuzz.ratio(s1, s2) for s2 in wpt_next['location']]
    #             max_ratio = max(ratios)
    #             [s2 for s2 in wpt_next['location'] if fuzz.partial_ratio(s1, s2) == max_ratio]
    #             [x for x in ]
    #
    #             wpt_next[wpt_next['mile'].str[0] == '1']
    #             # Do fuzzy match on location name and waypoint id?
    #
    #
    #         pass
    #         wpt_next[wpt_next['map'] == 'A13']
    #         wpt_this[wpt_this['waypoint'].isin(changed)]
    #         wpt_next['waypoint'].c
    #
    #         wpt_this
    #         break
    #     wpts_year
    #
    #     year = 2019
    #     dfi = df_dict[year]
    #     len(dfi)
    #     x = dfi.drop_duplicates(subset=['waypoint'])[wpt_cols]
    #     y = dfi.drop_duplicates(subset=wpt_cols)[wpt_cols]
    #     y.loc[y.duplicated(subset='waypoint', keep=False)].sort_values('waypoint')
    #     x
    #     df
    #     df_dict
    #
    #     #
    #     df[df['date'].dt.year > 2019]
    #     df['date'].dt.year.value_counts()
    #     df[df['date'].dt.year == 2011]
    #     sorted(df['date'].dt.year.unique())
    #     df
    #
    # def _list_google_sheets_files(self):
    #     """
    #     NOTE: was unable to get this to work. Each time I tried to list files, I got
    #     "Shared drive not found: 0B3jydhFdh1E2aVRaVEx0SlJPUGs"
    #     """
    #     from googleapiclient.discovery import build
    #     from google_auth_oauthlib.flow import InstalledAppFlow, Flow
    #
    #     client_secret_path = Path('~/.credentials/google_sheets_client_secret.json')
    #     client_secret_path = client_secret_path.expanduser().resolve()
    #
    #     flow = Flow.from_client_secrets_file(
    #         str(client_secret_path),
    #         scopes=['https://www.googleapis.com/auth/drive.readonly'],
    #         redirect_uri='urn:ietf:wg:oauth:2.0:oob')
    #
    #     # flow = InstalledAppFlow.from_client_secrets_file(
    #     #     str(client_secret_path),
    #     #     scopes=['drive', 'sheets'])
    #     auth_uri = flow.authorization_url()
    #     print(auth_uri[0])
    #
    #     token = flow.fetch_token(code='insert token from oauth screen')
    #     credentials = flow.credentials
    #
    #     # drive_service = build('drive', 'v3', developerKey=self.google_api_key)
    #     drive_service = build('drive', 'v3', credentials=credentials)
    #     results = drive_service.files().list(
    #         pageSize=10,
    #         q=("sharedWithMe"),
    #         driveId='0B3jydhFdh1E2aVRaVEx0SlJPUGs',
    #         includeItemsFromAllDrives=True,
    #         supportsAllDrives=True,
    #         corpora="drive",
    #         fields="*").execute()
    #     items = results.get('files', [])
    #     len(items)
