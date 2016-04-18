from __future__ import print_function
from builtins import str
import pandas as pd
from builtins import object


def _check_ctx(obj_type):
    from transcriptic import ctx
    if not ctx:
        raise RuntimeError("You have to be logged in to be able to create %s objects" % obj_type)
    return ctx


class ProtocolPreview(object):
    def __init__(self, protocol, connection):
        self.protocol = protocol
        self.preview_url = connection.preview_protocol(protocol)

    def _repr_html_(self):
        return """<iframe src="%s" frameborder="0" allowtransparency="true" \
        style="height:500px;" seamless></iframe>""" % self.preview_url


class _BaseObject(object):
    """Base object which other objects inherit from"""
    # TODO: Inherit more stuff from here. Need to ensure web has unified fields for objects
    def __init__(self, obj_type, obj_id, attributes, connection=None):
        # If attributes and connection are explicitly provided, just return and not do any smart parsing
        if attributes and connection:
            self.connection = connection
            self.attributes = attributes
        else:
            if not connection:
                self.connection = _check_ctx(obj_type)
            else:
                self.connection = connection
            (self.id, self.name) = self.load_object(obj_type, obj_id)
            if not attributes:
                self.attributes = self.connection._get_object(self.id)
            else:
                self.attributes = attributes

    def load_object(self, obj_type, obj_id):
        """Find and match object by name"""
        #TODO: Remove the try/except statement and properly handle cases where objects are not found
        try:
            objects = getattr(self.connection, obj_type + 's')()
        except:
            return (obj_id, str(obj_id))
        matched_objects = []
        for obj in objects:
            # Special case here since we use both 'name' and 'title' for object names
            if 'name' in obj:
                if obj_id == obj['name'] or obj_id == obj['id']:
                    matched_objects.append((obj['id'], obj['name']))
            if 'title' in obj:
                if obj_id == obj['title'] or obj_id == obj['id']:
                    matched_objects.append((obj['id'], obj['title']))
        if len(matched_objects) == 0:
            raise TypeError("%s is not found in your %ss." % (obj_id, obj_type))
        elif len(matched_objects) == 1:
            return matched_objects[0]
        else:
            print ("More than 1 match found. Defaulting to the first match: %s" % (matched_objects[0]))
            return matched_objects[0]



class Project(_BaseObject):
    """
    A Project object contains helper methods for managing your runs. For example, you can view the runs associated
    with this project.

    Example Usage:

    .. code-block:: python
        myProject = Project("My Project")
        projectRuns = myProject.runs()
        myRunId = projectRuns.query("title == 'myRun'").id.item()
        myRun = Run(myRunId)

    Attributes
    ----------
    id : str
        Project id
    name: str
        Project name
    attributes: dict
        Master attributes dictionary
    connection: transcriptic.config.Connection
        Transcriptic Connection object associated with this specific object

    """
    def __init__(self, project_id, attributes=None, connection=None):
        """
        Initialize a Project by providing a project name/id

        Parameters
        ----------
        project_id: str
            Project name or id in string form
        attributes: Optional[dict]
            Attributes of the object
        connection: Optional[transcriptic.config.Connection]
            Connection context. The default context object will be used unless explicitly provided
        """
        super(Project, self).__init__('project', project_id, attributes, connection)
        self._runs = pd.DataFrame()

    def runs(self, use_cache=True):
        """
        Get the list of runs belonging to the project

        Parameters
        ----------
        use_cache: Boolean
            Determines whether the cached list of runs is returned

        Returns
        -------
        DataFrame
            Returns a DataFrame of runs, with the id and title as columns
        """
        if self._runs.empty and use_cache:
            temp = self.connection.env_args
            self.connection.update_environment(project_id=self.id)
            project_runs = self.connection.runs()
            self._runs = pd.DataFrame([[pr['id'], pr['title']] for pr in project_runs])
            self._runs.columns = ['Id', 'Name']
            self.connection.env_args = temp
        return self._runs


    def submit(self, protocol, title, test_mode=False):
        """
        Submit a run under this project

        Parameters
        ----------
        protocol: dict
            Autoprotocol Protocol in dictionary form, can be generated using Protocol.as_dict()
        title: Optional[str]
            Title of run. Run-id will automatically be used as name if field is not provided
        test_mode: Optional[boolean]
            Determines if run will be submitted will be treated as a test run or a run that is meant for execution

        Returns
        -------
        Run
            Returns a run object if run is successfully submitted
        """
        response = self.connection.submit_run(protocol, project_id=self.id, title=title, test_mode=test_mode)
        return Run(response['id'], response)


class Run(_BaseObject):
    """
    A Run object contains helper methods for accessing Run-related information such as Instructions, Datasets
    and monitoring data

    Attributes
    ----------
    id : str
        Run id
    name: str
        Run name
    attributes: dict
        Master attributes dictionary
    connection: transcriptic.config.Connection
        Transcriptic Connection object associated with this specific object
    data: DataFrame
        Dictionary of all datasets which belong to this project
    instructions: List[Instructions]
        List of all Instruction objects for this project
    """
    def __init__(self, run_id, attributes=None, connection=None):
        """
        Initialize a Run by providing a run name/id

        Parameters
        ----------
        run_id: str
            Run name or id in string form
        attributes: Optional[dict]
            Attributes of the object
        connection: Optional[transcriptic.config.Connection]
            Connection context. The default context object will be used unless explicitly provided
        """
        super(Run, self).__init__('run', run_id, attributes, connection)
        self._instructions = None
        self._data = pd.DataFrame()

    @property
    def instructions(self):
        if not self._instructions:
            self._instructions = Instructions(self.attributes["instructions"])
        return self._instructions

    @property
    def data(self):
        """
        Find and generate a list of Dataset objects which are associated with this run

        Returns
        -------
        DataFrame
            Returns a DataFrame of datasets, with Name, Dataset and DataType as columns

        """
        if self._data.empty:
            datasets = self.connection.datasets(project_id=self.attributes['project']['url'], run_id=self.id)
            data_dict = {k: Dataset(datasets[k]["id"], dict(datasets[k], title=k),
                                    connection=self.connection)
                         for k in list(datasets.keys()) if datasets[k]}
            self._data = pd.DataFrame(sorted(list(data_dict.items()), key=lambda x: x[0]))
            self._data.columns = ["Name", "Dataset"]
            self._data.insert(1, "DataType", ([ds.operation for ds in self._data.Dataset]))
        return self._data

    def monitoring(self, instruction_id, data_type='pressure'):
        """
        View monitoring data of a given instruction

        Parameters
        ----------
        instruction_id: str
            Instruction id in string form
        data_type: str
            Monitoring data type, defaults to 'pressure'

        Returns
        -------
        DataFrame
            Returns a pandas dataframe of the monitoring data
        """
        response = self.connection.monitoring_data(
            project_id=self.attributes['project']['url'],
            run_id=self.id,
            instruction_id=instruction_id,
            data_type=data_type
        )
        return pd.DataFrame(response['results'])

    def _repr_html_(self):
        return """<iframe src="%s" frameborder="0" allowtransparency="true" \
        style="height:450px;" seamless></iframe>""" % \
               self.connection.get_route('view_run', project_id=self.attributes['project']['url'], run_id=self.id)


class Dataset(_BaseObject):
    """
    A Dataset object contains helper methods for accessing data related information

    Attributes
    ----------
    id : str
        Run id
    name: str
        Run name
    attributes: dict
        Master attributes dictionary
    connection: transcriptic.config.Connection
        Transcriptic Connection object associated with this specific object
    data : DataFrame
        DataFrame of raw data values. Note that associated metadata is found in attributes dictionary
    """
    def __init__(self, obj_id, attributes=None, connection=None):
        super(Dataset, self).__init__('dataset', obj_id, attributes, connection)
        # TODO: Get BaseObject to handle dataset name
        self.name = self.attributes["title"]
        self.id = obj_id
        self.operation = self.attributes["instruction"]["operation"]["op"]
        self.data_type = self.attributes["data_type"]
        self._data = pd.DataFrame()
        self.well_names = {aq["well_idx"]: aq["name"] for aq in self.attributes["container"]["aliquots"]}

    @property
    def data(self, key="*"):
        if self._data.empty:
            # Get all data initially (think about lazy loading in the future)
            self._data = pd.DataFrame(self.connection.dataset(data_id=self.id, key="*"))
            self._data.columns = [x.upper() for x in self._data.columns]
        if key == "*":
            return self._data
        else:
            return self._data[key]

    def _repr_html_(self):
        return """<iframe src="%s" frameborder="0" allowtransparency="true" \
            style="height:500px;width:450px" seamless></iframe>""" % \
               self.connection.get_route('view_data', data_id=self.id)


class Instructions(object):
    """
    An instruction object contains raw instructions as JSON as well as list of
    operations and warps generated from the raw instructions
    """

    def __init__(self, attributes):
        """
        Parameters
        ----------
        attributes : dict
            Instruction attributes
        """
        self.raw_instructions = attributes
        op_name_list = []
        op_warp_list = []
        for instruction in attributes:
            op_name_list.append(instruction["operation"]["op"])
            op_warp_list.append(instruction["warps"])
        instruct_dict = {}
        instruct_dict["name"] = op_name_list
        instruct_dict["warp_list"] = op_warp_list
        self.df = pd.DataFrame(instruct_dict)


class Container(_BaseObject):
    """
    A Container object represents a container from the Transcriptic LIMS and
    contains relevant information on the container type as well as the
    aliquots present in the container.

    Parameters
    ----------
    name: str
        Name of container
    wellMap: dict
        Well mapping with well indices for keys and well names as values
    aliquots: list
        List of aliquots present in the container
    containerType: autoprotocol.container_type.ContainerType
        Autoprotocol ContainerType object with many useful container type
        information and functions.

        Example Usage:

        .. code-block:: python

          my_container = container("ct186apgz6a374")

          my_container.wellMap

          my_container.containerType.col_count
          my_container.containerType.robotize("B1")
          my_container.containerType.humanize(12)


    """

    def __init__(self, obj_id, attributes=None, connection=None):
        # super(Container, self).__init__(obj_id, attributes, connection)
        # TODO: Unify container "label" with name, add Containers route
        self.id = obj_id
        self.name = self.attributes["label"]

        self.aliquots = self.attributes["aliquots"]
        self.wellMap = {aliquot["well_idx"]: aliquot["name"]
                        for aliquot in self.aliquots}
        self.containerType = self.parse_containerType()

    def _parse_containerType(self):
        from autoprotocol.container_type import _CONTAINER_TYPES
        from autoprotocol.container_type import ContainerType
        from copy import deepcopy
        containerType = deepcopy(self.attributes["container_type"])

        containerType.pop("well_type", None)
        containerType.pop("id", None)
        if "dead_volume" not in containerType:
            containerType["dead_volume_ul"] = _CONTAINER_TYPES[
                containerType["shortname"]].dead_volume_ul
        if "safe_min_volume_ul" not in containerType:
            containerType["safe_min_volume_ul"] = _CONTAINER_TYPES[
                containerType["shortname"]].safe_min_volume_ul

        return ContainerType(**containerType)

    def __repr__(self):
        """
        Return a string representation of a Container using the specified name.
        (ex. Container('my_plate'))

        """
        return "Container(%s)" % (str(self.name))


class Aliquot(_BaseObject):
    def __init__(self, obj_id, attributes=None, connection=False):
        super(Aliquot, self).__init__('aliquot', obj_id, attributes, connection)


class Resource(_BaseObject):
    def __init__(self, obj_id, attributes=None, connection=False):
        super(Resource, self).__init__('resource', obj_id, attributes, connection)
