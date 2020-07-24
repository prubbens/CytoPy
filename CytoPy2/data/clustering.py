from ..utilities import _valid_directory
from .experiments import Experiment
from dask import array
import mongoengine
import h5py
import os


class Cluster(mongoengine.EmbeddedDocument):
    """
    Represents a single cluster generated by a clustering experiment on a single file

    Parameters
    ----------
    cluster_id: str, required
        name associated to cluster
    index: FileField
        index of cell events associated to cluster (very large array)
    n_events: int, required
        number of events in cluster
    prop_of_root: float, required
        proportion of events in cluster relative to root population
    cluster_experiment: RefField
        reference to ClusteringDefinition
    meta_cluster_id: str, optional
        associated meta-cluster
    """
    cluster_id = mongoengine.StringField(required=True, unique=True)
    n_events = mongoengine.IntField(required=True)
    prop_of_root = mongoengine.FloatField(required=True)
    label = mongoengine.StringField(required=False)


class ClusteringExperiment(mongoengine.Document):
    experiment_name = mongoengine.StringField(required=True)
    data_directory = mongoengine.StringField(required=True, validation=_valid_directory)
    method = mongoengine.StringField(required=True, choices=["PhenoGraph", "FlowSOM"])
    parameters = mongoengine.ListField(required=True)
    features = mongoengine.ListField(required=True)
    transform_method = mongoengine.StringField(required=False, default="logicle")
    root_population = mongoengine.StringField(required=True, default="root")
    cluster_prefix = mongoengine.StringField(required=True, default="cluster")
    clusters = mongoengine.EmbeddedDocumentListField(Cluster)
    experiment = mongoengine.ReferenceField(Experiment, reverse_delete_rule=mongoengine.CASCADE)

    meta = {
        "db_alias": "core",
        "collection": "clustering_experiments"
    }

    def add_cluster(self,
                    cluster_idx: array,
                    root_n: int,
                    label: str or None = None):
        cluster_i = max([int(c.cluster_id.split("_")[1]) for c in self.clusters]) + 1
        f = h5py.File(os.path.join(self.data_directory, f"{self.id.__str__()}.hdf5"), "w")
        f.create_dataset(f"{self.cluster_prefix}_{cluster_i}", data=cluster_idx)
        f.close()
        self.clusters.append(Cluster(cluster_id=f"{self.cluster_prefix}_{cluster_i}",
                                     n_events=cluster_idx.shape[0],
                                     prop_of_root=cluster_idx.shape[0]/root_n,
                                     label=label))
        self.save()

    def remove_cluster(self,
                       cluster_id: str or None = None,
                       label: str or None = None):
        f = h5py.File(os.path.join(self.data_directory, f"{self.id.__str__()}.hdf5"), "w")
        if cluster_id:
            del f[cluster_id]
        elif label:
            del f[label]
        else:
            raise ValueError("Must provide either cluster ID or label")
        f.close()

    def label_cluster(self,
                      cluster_id: str,
                      label: str):
        cluster = [c for c in self.clusters if c.cluster_id == cluster_id][0]
        cluster.label = label

    def get_cluster(self,
                    cluster_id: str or None = None,
                    label: str or None = None):
        if cluster_id:
            del f[cluster_id]
        elif label:
            del f[label]
        else:
            raise ValueError("Must provide either cluster ID or label")


def _valid_meta_assignments(cluster_ids: list,
                            target: ClusteringExperiment):
    valid_clusters = [c.cluster_id for c in target.clusters]
    if not all([x in valid_clusters for x in cluster_ids]):
        raise mongoengine.errors.ValidationError("One or more clusters assigned by this meta clustering experiment "
                                                 "are not contained within the target clustering experiment")


class MetaClusters(mongoengine.EmbeddedDocument):
    cluster_id = mongoengine.StringField(required=True)
    _contents = mongoengine.ListField(required=True, db_field="contents")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "contents" in kwargs.keys():
            self.contents = kwargs.get("contents")

    @property
    def contents(self):
        return self._contents

    @contents.setter
    def contents(self, cluster_ids: list):
        valid_clusters = [c.cluster_id for c in self._instance.target.clusters]
        if not all([x in valid_clusters for x in cluster_ids]):
            raise ValueError("One or more clusters assigned by this meta clustering experiment "
                             "are not contained within the target clustering experiment")


class MetaClusteringExperiment(mongoengine.Document):
    experiment_name = mongoengine.StringField(required=True)
    method = mongoengine.StringField(required=True, choices=['PhenoGraph', 'FlowSOM', 'ConsensusClustering'])
    parameters = mongoengine.ListField(required=True)
    features = mongoengine.ListField(required=True)
    transform_method = mongoengine.StringField(required=False, default='logicle')
    target = mongoengine.ReferenceField(ClusteringExperiment, reverse_delete_rule=mongoengine.CASCADE)
    meta = {
        'db_alias': 'core',
        'collection': 'meta_clustering_experiments'
    }