#!/usr/bin.env/python
# -*- coding: utf-8 -*-
"""
Every analysis is controlled using the Project class, the highest
structure in the hierarchy of documents in the central MongoDB database.
You can create multiple experiments for a Project, each attaining to
a different staining panel. Experiments are accessed and managed through
the Project class.

Projects also house the subjects (represented by the Subject class;
see CytoPy.data.subject) of an analysis which can contain multiple
meta-data.

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

from .experiment import Experiment
from .subject import Subject
from typing import Generator
import mongoengine
import datetime

__author__ = "Ross Burton"
__copyright__ = "Copyright 2020, CytoPy"
__credits__ = ["Ross Burton", "Simone Cuff", "Andreas Artemiou", "Matthias Eberl"]
__license__ = "MIT"
__version__ = "1.0.0"
__maintainer__ = "Ross Burton"
__email__ = "burtonrj@cardiff.ac.uk"
__status__ = "Production"


class Project(mongoengine.Document):
    """
    A project is the highest controlling structure of an analysis and houses
    all the experiments, their associated FileGroups and the populations
    contained in each FileGroup and the populations clusters.

    Project can be used to create new experiments and to load existing experiments
    to interact with.

    Attributes
    ----------
    project_id: str, required
        unique identifier for project
    subjects: list
        List of references for associated subjects; see Subject
    start_date: DateTime
        date of creation
    owner: str, required
        user name of owner
    experiments: list
        List of references for associated fcs files
    """
    project_id = mongoengine.StringField(required=True, unique=True)
    subjects = mongoengine.ListField(mongoengine.ReferenceField(Subject, reverse_delete_rule=4))
    start_date = mongoengine.DateTimeField(default=datetime.datetime.now)
    owner = mongoengine.StringField(requred=True)
    experiments = mongoengine.ListField(mongoengine.ReferenceField(Experiment, reverse_delete_rule=4))

    meta = {
        'db_alias': 'core',
        'collection': 'projects'
    }

    def list_experiments(self) -> Generator:
        """
        Generate a list of associated flow cytometry experiments

        Returns
        -------
        Generator
            list of experiment IDs
        """
        for e in self.experiments:
            yield e.experiment_id

    def load_experiment(self, experiment_id: str) -> Experiment:
        """
        Load the experiment object for a given experiment ID

        Parameters
        ----------
        experiment_id: str
            experiment to load

        Returns
        --------
        Experiment
        """
        assert experiment_id in list(self.list_experiments()), f'Error: no experiment {experiment_id} found'
        return Experiment.objects(experiment_id=experiment_id).get()

    def add_experiment(self,
                       experiment_id: str,
                       data_directory: str,
                       panel_name: str or None = None,
                       panel_definition: str or None = None) -> Experiment:
        """
        Add new experiment to project. Note you must provide either a path to an excel template for the panel
        definition (panel_definition) or the name of an existing panel (panel_name). If panel_definition is provided,
        then the panel_name will be used to name the new Panel document associated to this experiment.
        If no panel_name is provided, then the panel name will default to "{experiment_id}_panel".

        Parameters
        -----------
        experiment_id: str
            experiment name
        data_directory: str
            Path where experiment events data files will be stored
        panel_name: str (optional)
            Name of panel to associate to experiment
        panel_definition: str (optional)
            Path to excel template for generating the panel

        Returns
        --------
        Experiment
            Newly created FCSExperiment
        """
        err = f'Error: Experiment with id {experiment_id} already exists!'
        assert experiment_id not in list(self.list_experiments()), err
        exp = Experiment(experiment_id=experiment_id,
                         panel_definition=panel_definition,
                         panel_name=panel_name,
                         data_directory=data_directory)
        exp.save()
        self.experiments.append(exp)
        self.save()
        return exp

    def add_subject(self,
                    subject_id: str,
                    drug_data: list or None = None,
                    infection_data: list or None = None,
                    patient_biology: list or None = None,
                    **kwargs) -> Subject:
        """
        Create a new subject and associated to project; a subject is an individual element of a study
        e.g. a patient or a mouse

        Parameters
        -----------
        subject_id: str
            subject ID for the new subject
        drug_data: list, optional
            list of Drug documents to associated to subject (see cytopy.data.subject.Drug)
        infection_data: list, optional
            list of Bug documents to associated to subject (see cytopy.data.subject.Bug)
        patient_biology: list, optional
            list of Biology documents to associated to subject (see cytopy.data.subject.Biology)
        kwargs:
            Additional keyword arguments to pass to Subject initialisation (see cytopy.data.subject.Subject)

        Returns
        --------
        None
        """
        new_subject = Subject(subject_id=subject_id, **kwargs)
        if drug_data is not None:
            new_subject.drug_data = drug_data
        if infection_data is not None:
            new_subject.infection_data = infection_data
        if patient_biology is not None:
            new_subject.patient_biology = patient_biology
        new_subject.save()
        self.subjects.append(new_subject)
        self.save()
        return new_subject

    def list_subjects(self) -> Generator:
        """
        Generate a list of subject ID for subjects associated to this project

        Returns
        --------
        Generator
            List of subject IDs
        """
        for s in self.subjects:
            yield s.subject_id

    def get_subject(self,
                    subject_id: str) -> Subject:
        """
        Given a subject ID associated to Project, return the Subject document

        Parameters
        -----------
        subject_id: str
            subject ID to pull

        Returns
        --------
        Subject
        """
        assert subject_id in list(self.list_subjects()), f'Invalid subject ID, valid subjects: ' \
                                                         f'{list(self.list_subjects())}'
        return Subject.objects(subject_id=subject_id).get()

    def delete(self, *args, **kwargs) -> None:
        """
        Delete project (wrapper function of mongoengine.Document.delete)

        Parameters
        -----------
        args:
            positional arguments to pass to parent call (see mongoengine.Document.delete)
        kwargs:
            keyword arguments to pass to parent call (see mongoengine.Document.delete)

        Returns
        --------
        None
        """
        experiments = [self.load_experiment(e) for e in list(self.list_experiments())]
        for e in experiments:
            samples = e.list_samples()
            for s in samples:
                e.remove_sample(s)
            e.delete()
        for p in self.subjects:
            p.delete()
        super().delete(*args, **kwargs)