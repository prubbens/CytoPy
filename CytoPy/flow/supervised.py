#!/usr/bin.env/python
# -*- coding: utf-8 -*-
"""
This module houses many of the utility functions for supervised
classification.

Copyright 2020 Ross Burton

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished
to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included
in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

from CytoPy.data.fcs import FileGroup
from sklearn.utils.class_weight import compute_class_weight
from sklearn import metrics as skmetrics
from xgboost import XGBClassifier
from sklearn.discriminant_analysis import *
from sklearn.neighbors import *
from sklearn.ensemble import *
from sklearn.svm import *
from keras.models import Sequential
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import inspect

__author__ = "Ross Burton"
__copyright__ = "Copyright 2020, CytoPy"
__credits__ = ["Ross Burton", "Simone Cuff", "Andreas Artemiou", "Matthias Eberl"]
__license__ = "MIT"
__version__ = "1.0.0"
__maintainer__ = "Ross Burton"
__email__ = "burtonrj@cardiff.ac.uk"
__status__ = "Production"


def build_sklearn_model(klass: str,
                        **params):
    """
    Initiate a SklearnClassifier object using Classes in the global environment

    Parameters
    ----------
    klass: str

    Returns
    -------
    object
    """
    assert klass in globals().keys(), \
        f"Module {klass} not found, is this a Scikit-Learn (or like) classifier? It might " \
        f"not currently be supported. See the docs for details."
    return globals()[klass](**params)


def build_keras_model(layers: list,
                      optimizer: str,
                      loss: str,
                      metrics: list,
                      **kwargs):
    """
    Create and compile a Keras Sequential model using the given KerasClassifier object

    Parameters
    ----------
    metrics: list
        See https://keras.io/api/metrics/
    loss: str
        See https://keras.io/api/losses/
    optimizer: str
        See https://keras.io/api/optimizers/
    layers: list
        List of Layer objects (see https://keras.io/api/layers/)

    Returns
    -------
    object
    """
    required_imports = [x.klass for x in layers]
    for i in required_imports:
        assert i in globals().keys(), f"Module {i} not found, have you imported it into " \
                                      f"the working environment?"
    model = Sequential()
    for layer in layers:
        keras_klass = globals()[layer.klass](**layer.kwargs)
        model.add(keras_klass)
    model.compile(optimizer=optimizer,
                  loss=loss,
                  metrics=metrics,
                  **kwargs)
    return model


def calc_metrics(metrics: list,
                 y_true: np.array,
                 y_pred: np.array or None = None,
                 y_score: np.array or None = None) -> dict:
    """
    Given a list of Scikit-Learn supported metrics (https://scikit-learn.org/stable/modules/model_evaluation.html)
    return a dictionary of results after checking that the required inputs are provided.

    Parameters
    ----------
    metrics: list
        List of string values; names of required metrics
    y_true: Numpy.Array
        True labels or binary label indicators. The binary and multiclass cases expect labels
        with shape (n_samples,) while the multilabel case expects binary label indicators with
        shape (n_samples, n_classes).
    y_pred: Numpy.Array
        Estimated targets as returned by a classifier
    y_score: Numpy.Array
        Target scores. In the binary and multilabel cases, these can be either probability
        estimates or non-thresholded decision values (as returned by decision_function on
        some classifiers). In the multiclass case, these must be probability estimates which
         sum to 1. The binary case expects a shape (n_samples,), and the scores must be the
         scores of the class with the greater label. The multiclass and multilabel cases expect
         a shape (n_samples, n_classes). In the multiclass case, the order of the class scores must
         correspond to the order of labels, if provided, or else to the numerical or
         lexicographical order of the labels in y_true.
    Returns
    -------
    dict
        Dictionary of performance metrics
    """
    results = dict()
    for m in metrics:
        if "f1" in m:
            avg = m.split("_")[1]
            f = getattr(skmetrics, "f1_score")
            assert y_pred is not None, "For F1 score predictions must be provided;`y_pred` is None"
            results[m] = f(y_true=y_true, y_pred=y_pred, average=avg)
        elif m == "roc_auc_score":
            f = getattr(skmetrics, m)
            results[m] = f(y_true=y_true,
                           y_score=y_score,
                           multi_class="ovo",
                           average="macro")
        else:
            f = getattr(skmetrics, m)
            if "y_score" in inspect.signature(f).parameters.keys():
                assert y_score is not None, f"Metric requested ({m}) requires probabilities of positive class but " \
                                            f"y_score not provided; y_score is None."
                results[m] = f(y_true=y_true, y_score=y_score)
            elif "y_pred" in inspect.signature(f).parameters.keys():
                results[m] = f(y_true=y_true, y_pred=y_pred)
            else:
                raise ValueError("Unexpected metric. Signature should contain either 'y_score' or 'y_pred'")
    return results


def confusion_matrix_plots(classifier,
                           x: pd.DataFrame,
                           y: np.ndarray,
                           class_labels: list,
                           cmap: str or None = None,
                           figsize: tuple = (10, 5),
                           **kwargs):
    """
    Generate a figure of two heatmaps showing a confusion matrix, one normalised
    by support one showing raw values, displaying a classifiers performance.
    Returns Matplotlib.Figure object.

    Parameters
    ----------
    classifier: object
        Scikit-Learn classifier
    x: Pandas.DataFrame
        Feature space
    y: Numpy.Array
        Labels
    class_labels: list
        Class labels (as they should be displayed on the axis)
    cmap: str
        Colour scheme, defaults to Matplotlib Blues
    figsize: tuple (default=(10,5))
        Size of the figure
    kwargs:
        Additional keyword arguments passed to sklearn.metrics.plot_confusion_matrix

    Returns
    -------
    Matplotlib.Figure
    """
    cmap = cmap or plt.cm.Blues
    fig, axes = plt.subplots(2, figsize=figsize)
    titles = ["Confusion matrix, without normalisation", "Confusion matrix; normalised"]
    for i, (title, norm) in enumerate(zip(titles, [False, True])):
        skmetrics.plot_confusion_matrix(estimator=classifier,
                                        X=x,
                                        y=y,
                                        display_labels=class_labels,
                                        cmap=cmap,
                                        normalize=norm,
                                        ax=axes[i],
                                        **kwargs)
        axes[i].set_title(title)
    return fig


def assert_population_labels(ref: FileGroup,
                             expected_labels: list):
    """
    Given some reference FileGroup and the expected population labels, check the
    validity of the labels and return list of valid populations only.

    Parameters
    ----------
    ref: FileGroup
    expected_labels: list

    Returns
    -------
    List
    """
    assert len(ref.populations) >= 2, "Reference sample does not contain any gated populations"
    for x in expected_labels:
        assert x in ref.tree.keys(), f"Ref FileGroup missing expected population {x}"


def check_downstream_populations(ref: FileGroup,
                                 root_population: str,
                                 population_labels: list) -> None:
    """
    Check that in the ordered list of population labels, all populaitons are downstream 
    of the given 'root' population.

    Parameters
    ----------
    ref: FileGroup
    root_population: str
    population_labels: list

    Returns
    -------
    None
    """
    downstream = ref.list_downstream_populations(root_population)
    assert all([x in downstream for x in population_labels]), \
        "The first population in population_labels should be the 'root' population, with all further populations " \
        "being downstream from this 'root'. The given population_labels has one or more populations that is not " \
        "downstream from the given root."


def multilabel(ref: FileGroup,
               root_population: str,
               population_labels: list,
               transform: str,
               features: list) -> (pd.DataFrame, pd.DataFrame):
    """
    Load the root population DataFrame from the reference FileGroup (assumed to be the first
    population in 'population_labels'). Then iterate over the remaining population creating a
    dummy matrix of population affiliations for each row of the root population.

    Parameters
    ----------
    ref: FileGroup
    population_labels: list
    transform: str
    features: list

    Returns
    -------
    (Pandas.DataFrame, Pandas.DataFrame)
        Root population flourescent intensity values, population affiliations (dummy matrix)
    """
    root = ref.load_population_df(population=root_population,
                                  transform=transform)
    for pop in population_labels:
        root[pop] = 0
        root.loc[ref.get_population(pop).index, pop] = 1
    return root[features], root[population_labels]


def singlelabel(ref: FileGroup,
                root_population: str,
                population_labels: list,
                transform: str,
                features: list) -> (pd.DataFrame, np.ndarray):
    """
    Load the root population DataFrame from the reference FileGroup (assumed to be the first
    population in 'population_labels'). Then iterate over the remaining population creating a
    Array of population affiliations; each cell (row) is associated to their terminal leaf node
    in the FileGroup population tree.

    Parameters
    ----------
    root_population
    ref: FileGroup
    population_labels: list
    transform: str
    features: list

    Returns
    -------
    (Pandas.DataFrame, Numpy.Array)
        Root population flourescent intensity values, labels
    """
    root = ref.load_population_df(population=root_population,
                                  transform=transform)
    root["label"] = 0
    for i, pop in enumerate(population_labels):
        pop_idx = ref.get_population(population_name=pop).index
        root.loc[pop_idx, "label"] = i + 1
    y = root["label"].values
    root.drop("label", axis=1, inplace=True)
    return root[features], y


def auto_weights(y: np.ndarray):
    """
    Estimate optimal weights from a list of class labels.

    Parameters
    ----------
    y: Numpy.Array

    Returns
    -------
    dict
        Dictionary of class weights {label: weight}
    """
    classes = np.unique(y)
    weights = compute_class_weight('balanced',
                                   classes=classes,
                                   y=y)
    return {i: w for i, w in enumerate(weights)}
