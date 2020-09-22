from ..data.populations import Cluster, PopulationGeometry, Population
from shapely.geometry import Polygon
import numpy as np
import pytest


def test_cluster_init():
    x = Cluster(cluster_id="test",
                n=1000)
    x.index = [0, 1, 2, 3, 4]
    assert np.array_equal(np.array([0, 1, 2, 3, 4]), x.index)
    x = Cluster(cluster_id="test",
                n=1000,
                index=[0, 1, 2, 3, 4])
    assert np.array_equal(np.array([0, 1, 2, 3, 4]), x.index)


def test_population_geometry_shape():
    poly = PopulationGeometry(x_values=[0, 0, 5, 5, 0],
                              y_values=[0, 5, 5, 0, 0])
    assert isinstance(poly.shape, Polygon)
    assert np.array_equal(poly.shape.exterior.xy[0], np.array([0, 0, 5, 5, 0]))
    assert np.array_equal(poly.shape.exterior.xy[1], np.array([0, 5, 5, 0, 0]))
    circle = PopulationGeometry(width=5,
                                height=5,
                                center=(10, 10),
                                angle=0)
    assert isinstance(circle.shape, Polygon)
    assert circle.shape.area == pytest.approx(np.pi * (circle.width ** 2), 1.)
    threshold = PopulationGeometry(x_threshold=2.5,
                                   y_threshold=2.5)
    assert threshold.shape is None


def test_population_geometry_overlap():
    threshold = PopulationGeometry(x_threshold=2.5,
                                   y_threshold=2.5)
    poly1 = PopulationGeometry(x_values=[0, 0, 5, 5, 0],
                               y_values=[0, 5, 5, 0, 0])
    poly2 = PopulationGeometry(x_values=[2.5, 2.5, 5, 5, 2.5],
                               y_values=[0, 5, 5, 0, 0])
    with pytest.warns(UserWarning) as w:
        threshold.overlap(poly1)
    assert str(w.list[0].message) == "PopulationGeometry properties are incomplete. Cannot determine shape."
    assert poly1.overlap(poly2.shape) == 0.5
    assert poly2.overlap(poly1.shape) == 1.0
    assert poly1.overlap(poly2.shape, 0.6) == 0.0
    assert poly2.overlap(poly1.shape, 0.6) == 1.0


def test_population_init():
    x = Population
