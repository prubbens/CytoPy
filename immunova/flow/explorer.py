# Immunova
from mongoengine.base.datastructures import EmbeddedDocumentList
from immunova.data.fcs_experiments import FCSExperiment
from immunova.data.explorer import ExplorerData, DimReduction
from immunova.data.patient import Patient, Bug
from immunova.flow.gating.actions import Gating
from immunova.flow.utilities import progress_bar
from immunova.flow.dim_reduction import dimensionality_reduction
from immunova.flow.utilities import which_environment
# Interactive plotting
from bokeh.io import output_file, save, show, output_notebook
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, BoxSelectTool, CustomJS
from bokeh.models.widgets import TextAreaInput
from bokeh.layouts import row
# SciPy
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
# AnyTree
from anytree.node import Node
# Other
import phenograph
import scprep



class Explorer:
    """
    Using a dimensionality reduction technique, explore high dimensional flow cytometry data.
    """

    def __init__(self, root_population: str = 'root', transform: str or None = 'logicle',
                 load_existing: str or None = None):
        """
        :param root_population: data included in the indicated population will be pulled from each file
        :param transform: transform to be applied to each sample, provide a value of None to use raw data
        :param load_existing: give name of database record if you wish to load an
        existing exploration project (optional)
        (default = 'logicle')
        population of each file group (optional)
        """
        self.data = pd.DataFrame()
        self.transform = transform
        self.root_population = root_population
        self.cache = dict()

        if load_existing is not None:
            db = ExplorerData.objects(name=load_existing)
            if not db:
                raise ValueError(f'{load_existing} does not exist!')
            existing = db[0].load()
            self.data = existing['data']
            self.transform = existing['transform']
            self.root_population = existing['root_population']
            if existing['cache'] is not None:
                self.cache = existing['cache']

    def clear_data(self):
        """
        Clear existing data and cache.
        """
        self.data = pd.DataFrame()
        self.cache = dict()

    def save_data(self, name: str):
        """
        Save the results generated by this explorer object to database
        :param name: Unique identifier to associate to database record
        :return: None
        """
        if ExplorerData.objects(name=name):
            raise ValueError(f'{name} already exists in database. If you wish to overwrite this record, first delete '
                             f'by loading the ExplorerData object and calling the Delete() method')
        db = ExplorerData()
        db.name = name
        db.transform = self.transform
        db.root_population = self.root_population
        db.put(self.data)

        if self.cache:
            dr_db = DimReduction()
            dr_db.method = self.cache['method']
            dr_db.features = self.cache['features']
            dr_db.put(self.cache['data'])
            db.cache = dr_db
        db.save()

    def load_data(self, experiment: FCSExperiment, samples: list, sample_n: None or int = None):
        """
        Load fcs file data, including any associated gates or clusters
        :param experiment: FCSExperiment to load samples from
        :param samples: list of sample IDs
        :param sample_n: if an integer value is provided, each file will be downsampled to the indicated
        amount (optional)
        """
        print(f'------------ Loading flow data: {experiment.experiment_id} ------------')
        for sid in progress_bar(samples):
            g = Gating(experiment, sid, include_controls=False)
            if self.transform is not None:
                fdata = g.get_population_df(population_name=self.root_population,
                                            transform=True,
                                            transform_method=self.transform)
            else:
                fdata = g.get_population_df(population_name=self.root_population)
            if fdata is None:
                raise ValueError(f'Population {self.root_population} does not exist for {sid}')
            if sample_n is not None:
                if sample_n < fdata.shape[0]:
                    fdata = fdata.sample(n=sample_n)
            fdata = self.__population_labels(fdata, g.populations[self.root_population])
            fdata = fdata.reset_index()
            fdata = fdata.rename({'index': 'original_index'}, axis=1)
            pt = Patient.objects(files__contains=g.mongo_id)
            if pt:
                fdata['pt_id'] = pt[0].patient_id
            else:
                print(f'File group {g.id} in experiment {experiment.experiment_id} is not associated to any patient')
                fdata['pt_id'] = 'NONE'
            self.data = pd.concat([self.data, fdata])
        print('------------ Completed! ------------')

    def __population_labels(self, data: pd.DataFrame, root_node: Node) -> pd.DataFrame:
        """
        Internal function. Called when loading data. Populates DataFrame column named 'population_label' with the
        name of the node associated with each event most downstream of the root population.
        :param data: Pandas DataFrame of events corresponding to root population from single patient
        :param root_node: anytree Node object of root population
        :return: Pandas DataFrame with 'population_label' column
        """

        def recursive_label(d, n):
            mask = d.index.isin(n.index)
            d.loc[mask, 'population_label'] = n.name
            if len(n.children) == 0:
                return d
            for c in n.children:
                recursive_label(d, c)
            return d

        data = data.copy()
        data['population_label'] = self.root_population
        data = recursive_label(data, root_node)
        return data

    def load_meta(self, variable: str):
        """
        Load meta data for each patient. Must be provided with a variable that is a field with a single value
        NOT an embedded document. A column will be generated in the Pandas DataFrame stored in the attribute 'data'
        that pertains to the variable given and the value will correspond to that of the patients.
        :param variable: field name to populate data with
        """
        self.data[variable] = 'NONE'
        for pt_id in progress_bar(self.data.pt_id.unique()):
            if pt_id == 'NONE':
                continue
            p = Patient.objects(patient_id=pt_id).get()
            if type(p[variable]) == EmbeddedDocumentList:
                raise TypeError('Chosen variable is an embedded document.')
            self.data.loc[self.data.pt_id == pt_id, variable] = p[variable]

    def load_infectious_data(self, multi_org: str = 'list'):
        """
        Load the bug data from each patient and populate 'data' accordingly. As default variables will be created as
        follows:
        * organism_name = If 'multi_org' equals 'list' then multiple organisms will be stored as a comma separated list
        without duplicates, whereas if the value is 'mixed' then multiple organisms will result in a value of 'mixed'.
        * organism_type = value of either 'gram positive', 'gram negative', 'virus', 'mixed' or 'fungal'
        * hmbpp = True or False based on HMBPP status (Note: it only takes one positive organism for this value to be
        True)
        * ribo = True or False based on Ribo status (Note: it only takes one positive organism for this value to be
        True)
        """
        self.data['organism_name'] = 'Unknown'
        self.data['organism_type'] = 'Unknown'
        self.data['hmbpp'] = 'Unknown'
        self.data['ribo'] = 'Unknown'

        for pt_id in progress_bar(self.data.pt_id.unique()):
            if pt_id == 'NONE':
                continue
            p = Patient.objects(patient_id=pt_id).get()
            self.data.loc[self.data.pt_id == pt_id, 'organism_name'] = self.__bugs(patient=p, multi_org=multi_org)
            self.data.loc[self.data.pt_id == pt_id, 'organism_type'] = self.__org_type(patient=p)
            self.data.loc[self.data.pt_id == pt_id, 'hmbpp'] = self.__hmbpp_ribo(patient=p, field='hmbpp_status')
            self.data.loc[self.data.pt_id == pt_id, 'ribo'] = self.__hmbpp_ribo(patient=p, field='ribo_status')

    @staticmethod
    def __bugs(patient: Patient, multi_org: str) -> str:
        """
        Internal function. Fetch the name of isolated organisms for each patient.
        :param patient: Patient model object
        :param multi_org: If 'multi_org' equals 'list' then multiple organisms will be stored as a comma separated list
        without duplicates, whereas if the value is 'mixed' then multiple organisms will result in a value of 'mixed'.
        :return: string of isolated organisms comma seperated, or 'mixed' if multi_org == 'mixed' and multiple organisms
        listed for patient
        """
        if not patient.infection_data:
            return 'Unknown'
        orgs = [b.org_name for b in patient.infection_data if b.org_name]
        if not orgs:
            return 'Unknown'
        if len(orgs) == 1:
            return orgs[0]
        if multi_org == 'list':
            return ','.join(orgs)
        return 'mixed'

    @staticmethod
    def __org_type(patient: Patient) -> str:
        """
        Parse all infectious isolates for each patient and return the organism type isolated, one of either:
        'gram positive', 'gram negative', 'virus', 'mixed' or 'fungal'
        :param patient: Patient model object
        :return: common organism type isolated for patient
        """

        def bug_type(b: Bug):
            if not b.organism_type:
                return 'Unknown'
            if b.organism_type == 'bacteria':
                return b.gram_status
            return b.organism_type

        bugs = list(set(map(bug_type, patient.infection_data)))
        if len(bugs) == 0:
            return 'Unknown'
        if len(bugs) == 1:
            return bugs[0]
        return 'mixed'

    @staticmethod
    def __hmbpp_ribo(patient: Patient, field: str) -> str:
        """
        Given a value of either 'hmbpp' or 'ribo' for 'field' argument, return True if any Bug has a positive status
        for the given patient ID.
        :param patient: Patient model object
        :param field: field name to search for; expecting either 'hmbpp_status' or 'ribo_status'
        :return: common value of hmbpp_status/ribo_status
        """
        if all([b[field] is None for b in patient.infection_data]):
            return 'Unknown'
        if all([b[field] == 'P+ve' for b in patient.infection_data]):
            return 'P+ve'
        if all([b[field] == 'N-ve' for b in patient.infection_data]):
            return 'N-ve'
        return 'mixed'

    def load_biology_data(self, test_name: str, summary_method: str = 'average'):
        """
        Load the pathology results of a given test from each patient and populate 'data' accordingly. As multiple
        results may exist for one particular test, a summary method should be provided, this should have a value as
        follows:
        * average - the average test result is generated and stored
        * max - the maximum value is stored
        * min - the minimum value is stored
        * median - the median test result is generated and stored
        """
        self.data[test_name] = self.data['pt_id'].apply(lambda x: self.__biology(x, test_name, summary_method))

    @staticmethod
    def __biology(pt_id: str, test_name: str, method: str) -> np.float or None:
        """
        Given some test name, return a summary statistic of all results for a given patient ID
        :param pt_id: patient identifier
        :param test_name: name of test to search for
        :param method: summary statistic to use
        """
        if pt_id == 'NONE':
            return None
        tests = Patient.objects(patient_id=pt_id).get().patient_biology
        tests = [t.result for t in tests if t.test == test_name]
        if not tests:
            return None
        if method == 'max':
            return np.max(tests)
        if method == 'min':
            return np.min(tests)
        if method == 'median':
            return np.median(tests)
        return np.average(tests)

    def __plotting_labels(self, label: str, populations: list or None):
        """
        Internal function called by plotting functions to generate array that will be used for the colour property
        of each data point.
        :param label: string value of the label option (see scatter_plot method)
        :param populations: list of populations to include if label = 'gated populations' (optional)
        """
        if label in self.data.columns:
            return self.data[label].values
        elif label == 'global clusters':
            if 'PhenoGraph labels' not in self.data.columns:
                raise ValueError('Must call phenograph_clustering method prior to plotting PhenoGraph clusters')
            return self.data['PhenoGraph labels'].values
        elif label == 'gated populations':
            if populations:
                return np.array(list(map(lambda x: x if x in populations else 'None',
                                         self.data['population_label'].values)))
            return self.data['population_label'].values
        raise ValueError(f'Label {label} is invalid; must be either a column name in the existing dataframe '
                         f'({self.data.columns.tolist()}), "global clusters" which labels events according to '
                         f'clustering on the concatenated dataset, or "gated populations" which are common populations '
                         f'gated on a per sample basis.')

    def get_cache(self, method: str, features: list) -> np.array or None:
        """
        Return the cached embeddings if given method and features match cache.
        :param method: dimensionality reduction method
        :param features: list of features used for dimensionality reduction
        :return: Numpy array of embeddings if matched, else None
        """
        if len(self.cache.keys()) == 0:
            return None
        if self.cache['method'] == method and self.cache['features'] == features:
            return self.cache['data']
        return None

    def __dim_reduction(self, dim_reduction_method: str, features: list,
                        n_components: int = 2, use_cache: bool = True, **kwargs):
        if use_cache:
            embeddings = self.get_cache(method=dim_reduction_method, features=features)
            if embeddings is None:
                embeddings = dimensionality_reduction(self.data, features, dim_reduction_method,
                                                      n_components, return_embeddings_only=True,
                                                      **kwargs)
                self.cache['method'] = dim_reduction_method
                self.cache['features'] = features
                self.cache['data'] = embeddings
        else:
            embeddings = dimensionality_reduction(self.data, features, dim_reduction_method,
                                                  n_components, return_embeddings_only=True,
                                                  **kwargs)
        return embeddings

    def scatter_plot(self, primary_label: str, features: list, secondary_label: str or None = None,
                     populations: list or None = None, n_components: int = 2,
                     dim_reduction_method: str = 'UMAP', use_cache: bool = True, **kwargs) -> plt.Axes:
        """
        Generate a 2D/3D scatter plot (dimensions depends on the number of components chosen for dimensionality
        reduction. Each data point is labelled according to the option provided to the label arguments. If a value
        is given to both primary and secondary label, the secondary label colours the background and the primary label
        colours the foreground of each datapoint.
        :param primary_label: option for the primary label, must be one of the following:
        * A valid column name in Explorer attribute 'data' (check valid column names using Explorer.data.columns)
        * 'global clusters' - requires that phenograph_clustering method has been called prior to plotting. Each data
        point will be coloured according to cluster association.
        * 'gated populations' - each data point is coloured according to population identified by prior gating
        :param features: list of column names used as feature space for dimensionality reduction
        :param secondary_label: option for the secondary label, options same as primary_label (optional)
        :param populations: if primary/secondary label has value of 'gated populations', only populations in this
        list will be included (events with no population associated will be labelled 'None')
        :param n_components: number of components to produce from dimensionality reduction, valid values are 2 or 3
        (default = 2)
        :param dim_reduction_method: method to use for dimensionality reduction, valid values are 'UMAP' or 'PHATE'
        (default = 'UMAP')
        :param use_cache: dimensionality reduction can be computationally expensive. If use_cache = True, then the
        results of this calculation are stored in an internal attribute named 'cache'. Only one cache can be stored
        at a time and has the structure {'method': 'UMAP' or 'PHATE', 'features': list of features used in calculation,
        'data': embeddings}. If use_cache is True and the features and method match that in 'cache', results are
        loaded directly from the cache, otherwise dim reduction is performed again and cache is overwritten.
        :param kwargs: additional keyword arguments to pass to dimensionality reduction algorithm
        :return: matplotlib subplot axes object
        """
        fig, ax = plt.subplots(figsize=(12, 8))
        if n_components not in [2, 3]:
            raise ValueError('n_components must have a value of 2 or 3')

        # Dimensionality reduction
        embeddings = self.__dim_reduction(dim_reduction_method=dim_reduction_method,
                                          features=features, use_cache=use_cache,
                                          n_components=n_components, **kwargs)
        # Label and plotting
        plabel = self.__plotting_labels(primary_label, populations)
        if secondary_label is not None:
            slabel = self.__plotting_labels(secondary_label, populations)
            if n_components == 2:
                ax = scprep.plot.scatter2d(embeddings, c=slabel, ticks=False,
                                           label_prefix=dim_reduction_method, ax=ax, s=100,
                                           discrete=self.__discrete(slabel), legend_loc="lower left",
                                           legend_anchor=(1.04, 1), legend_title=secondary_label)

            else:
                ax = scprep.plot.scatter3d(embeddings, c=slabel, ticks=False,
                                           label_prefix=dim_reduction_method, ax=ax, s=100,
                                           discrete=self.__discrete(slabel), legend_loc="lower left",
                                           legend_anchor=(1.04, 1), legend_title=secondary_label)
        if n_components == 2:
            ax = scprep.plot.scatter2d(embeddings, c=plabel, ticks=False,
                                       label_prefix=dim_reduction_method, ax=ax, s=1,
                                       discrete=self.__discrete(plabel), legend_loc="lower left",
                                       legend_anchor=(1.04, 0), legend_title=primary_label)
        else:
            ax = scprep.plot.scatter3d(embeddings, c=plabel, ticks=False,
                                       label_prefix=dim_reduction_method, ax=ax, s=1,
                                       discrete=self.__discrete(plabel), legend_loc="lower left",
                                       legend_anchor=(1.04, 0), legend_title=primary_label)
        return ax

    def heatmap(self, heatmap_var: str, features: list, clustermap: bool = False):
        """
        Generate a heatmap of marker expression for either global clusters or gated populations
        (indicated with 'heatmap_var' argument)
        :param heatmap_var: variable to use, either 'global clusters' or 'gated populations'
        :param features: list of column names to use for generating heatmap
        :param clustermap: if True, rows (clusters/populations) are grouped by single linkage clustering
        """
        if heatmap_var == 'global clusters':
            heatmap_var = 'PhenoGraph labels'
        elif heatmap_var == 'gated populations':
            heatmap_var = 'population_label'
        else:
            raise ValueError('Error: heatmap_var must have value of either "global clusters" or "PhenoGraph labels", '
                             f'not {heatmap_var}')
        d = self.data[features + [heatmap_var]]
        d[features] = d[features].apply(pd.to_numeric)
        d = d.groupby(by=heatmap_var).mean()
        if clustermap:
            ax = sns.clustermap(d, col_cluster=False, cmap='viridis', figsize=(16, 10))
            return ax
        fig, ax = plt.subplots(figsize=(16, 10))
        ax = sns.heatmap(d, linewidth=0.5, ax=ax, cmap='viridis')
        ax.set_title('MFI (averaged over all patients) for PhenoGraph clusters')
        return ax

    def cluster_representation(self, variable: str, discrete: bool = True):
        """
        Present a breakdown of how a variable is represented within each cluster
        :param variable: name of variable to plot
        :param discrete: if True, the variable is assumed to be discrete
        :return: matplotlib axes object
        """
        if variable == 'patient representation':
            x = self.data[['PhenoGraph labels', 'pt_id']].groupby('PhenoGraph labels')['pt_id'].nunique() / len(
                self.data.pt_id.unique()) * 100
            fig, ax = plt.subplots(figsize=(12, 7))
            x.sort_values().plot(kind='bar', ax=ax)
            ax.set_ylabel('Patient represenation (%)')
            ax.set_xlabel('Global PhenoGraph Clusters')
            return ax
        if variable in self.data.columns and discrete:
            x = (self.data[['PhenoGraph labels', variable]].groupby('PhenoGraph labels')[variable]
                 .value_counts(normalize=True)
                 .rename('percentage')
                 .mul(100)
                 .reset_index()
                 .sort_values(variable))
            fig, ax = plt.subplots(figsize=(12, 7))
            p = sns.barplot(x="PhenoGraph labels", y="percentage", hue=variable, data=x, ax=ax)
            _ = plt.setp(p.get_xticklabels(), rotation=90)
            ax.set_ylabel(f'% cells ({variable})')
            ax.set_xlabel('Global PhenoGraph Clusters')
            return ax
        if variable in self.data.columns and not discrete:
            fig, ax = plt.subplots(figsize=(15, 5))
            d = self.data.sample(10000)
            ax = sns.swarmplot(x='PhenoGraph labels', y=variable, data=d, ax=ax, s=3)
            return ax

    @staticmethod
    def __discrete(labels):
        if all([type(x) == float for x in labels]):
            return False
        return True

    def phenograph_clustering(self, features: list, **kwargs):
        """
        Using the PhenoGraph clustering algorithm, cluster all events in concatenated dataset.
        :param features: list of features to perform clustering on
        :param kwargs: keyword arguments to pass to PhenoGraph clustering object
        """
        communities, graph, q = phenograph.cluster(self.data[features], **kwargs)
        self.data['PhenoGraph labels'] = communities

    def select_cells(self, dim_reduction_method: str, features: list, colour: str = 'global clusters',
                     use_cache: bool = True, n_components: int = 2, output_path: str or None = None, **kwargs):
        env = which_environment()
        if env == 'jupyter':
            output_notebook()
        else:
            if output_path is None:
                raise ValueError("If you're not running in a Jupyter Notebook environment, you must provide an output "
                                 "path for the resulting HTML file")
        # Dimensionality reduction
        embeddings = self.__dim_reduction(dim_reduction_method=dim_reduction_method,
                                          features=features, use_cache=use_cache,
                                          n_components=n_components, **kwargs)
        if colour == 'global clusters':
            colour = 'PhenoGraph labels'
        elif colour == 'gated populations':
            colour = 'population_label'
        else:
            raise ValueError('Error: "colour" must have value of either "global clusters" or "PhenoGraph labels", '
                             f'not {colour}')
        sc_data = dict(x=list(embeddings[:, 0]),
                       y=list(embeddings[:, 1]),
                       fill=self.data[colour],
                       patient=self.data['pt_id'],
                       cluster=self.data['PhenoGraph labels'],
                       population=self.data['population_label'],
                       index=self.data.index)
        sc_data = ColumnDataSource(data=sc_data)
        # colour_map = [cc.rainbow[i * 5] for i in range(len(self.data[colour].unique()))]
        tools = "hover,save,reset,box_zoom,box_select"
        text_output = TextAreaInput(value="Select data points...", title="Selection index:",
                                         rows=12)
        q = figure(tools=tools, plot_width=500, plot_height=500, toolbar_location='below')
        q.circle(x='x', y='y', source=sc_data, fill_alpha=0.4, line_alpha=0.4, size=2,
                 fill_color='fill')
        select_tool = q.select(dict(type=BoxSelectTool))
        sc_data.callback = CustomJS(args=dict(q=q), code="""
            var inds = cb_obj.get('selected')['1d'].indices;
            var d1 = cb_obj.get('data');
            console.log(d1)
            var kernel = IPython.notebook.kernel;
            IPython.notebook.kernel.execute("inds = " + inds);
        """)
        layout = row(q, text_output)
        if env != 'jupyter':
            output_file(output_path, layout)
            save(layout)
        show(layout)