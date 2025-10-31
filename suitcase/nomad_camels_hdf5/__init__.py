# Suitcase subpackages should follow strict naming and interface conventions.
# The public API must include Serializer and should include export if it is
# intended to be user-facing. They should accept the parameters sketched here,
# but may also accpet additional required or optional keyword arguments, as
# needed.
import event_model
import os
import sys
import importlib.metadata
from pathlib import Path
import numpy as np
import h5py
from suitcase.utils import SuitcaseUtilsValueError
import collections
from ._version import get_versions
from datetime import datetime as dt
import databroker
import databroker.core
import copy
import ast
import json

__version__ = get_versions()["version"]
del get_versions


def get_variables_from_expression(s):
    """
    Parses an expression and returns a set of all
    variable names and numeric constants.
    """
    # 1. Parse the string into an Abstract Syntax Tree
    #    We use 'eval' mode because it's a single expression.
    # Clean the string by replacing np.*() calls with *()
    s = s.replace("np.", "")
    try:
        tree = ast.parse(s, mode='eval')
    except SyntaxError:
        print(f"Error: Invalid syntax '{s}'")
        return set()

    variables = set()
    
    # 2. "Walk" the tree to find all nodes
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            # ast.Name nodes are variables like 'var1', 'x', etc.
            variables.add(node.id)
        elif isinstance(node, ast.Constant):
            # ast.Constant nodes are literals like 5, 1.2, 'hello'
            # We check if it's a number, per your request.
            if isinstance(node.value, (int, float)):
                variables.add(node.value)
                
    return variables

def export(
    gen, directory, file_prefix="{uid}-", new_file_each=True, plot_data=None, **kwargs
):
    """
    Export a stream of documents to nomad_camels_hdf5.

    .. note::

        This can alternatively be used to write data to generic buffers rather
        than creating files on disk. See the documentation for the
        ``directory`` parameter below.

    Parameters
    ----------
    gen : generator
        expected to yield ``(name, document)`` pairs

    directory : string, Path or Manager.
        For basic uses, this should be the path to the output directory given
        as a string or Path object. Use an empty string ``''`` to place files
        in the current working directory.

        In advanced applications, this may direct the serialized output to a
        memory buffer, network socket, or other writable buffer. It should be
        an instance of ``suitcase.utils.MemoryBufferManager`` and
        ``suitcase.utils.MultiFileManager`` or any object implementing that
        interface. See the suitcase documentation at
        https://nsls-ii.github.io/suitcase for details.

    file_prefix : str, optional
        The first part of the filename of the generated output files. This
        string may include templates as in ``{proposal_id}-{sample_name}-``,
        which are populated from the RunStart document. The default value is
        ``{uid}-`` which is guaranteed to be present and unique. A more
        descriptive value depends on the application and is therefore left to
        the user.

    **kwargs : kwargs
        Keyword arugments to be passed through to the underlying I/O library.

    Returns
    -------
    artifacts : dict
        dict mapping the 'labels' to lists of file names (or, in general,
        whatever resources are produced by the Manager)

    Examples
    --------

    Generate files with unique-identifier names in the current directory.

    >>> export(gen, '')

    Generate files with more readable metadata in the file names.

    >>> export(gen, '', '{plan_name}-{motors}-')

    Include the measurement's start time formatted as YYYY-MM-DD_HH-MM.

    >>> export(gen, '', '{time:%Y-%m-%d_%H:%M}-')

    Place the files in a different directory, such as on a mounted USB stick.

    >>> export(gen, '/path/to/my_usb_stick')
    """
    with Serializer(
        directory,
        file_prefix,
        new_file_each=new_file_each,
        plot_data=plot_data,
        **kwargs,
    ) as serializer:
        for item in gen:
            serializer(*item)

    return serializer.artifacts


def clean_filename(filename):
    """
    cleans the filename from characters that are not allowed

    Parameters
    ----------
    filename : str
        The filename to clean.
    """
    filename = filename.replace(" ", "_")
    filename = filename.replace(".", "_")
    filename = filename.replace(":", "-")
    filename = filename.replace("/", "-")
    filename = filename.replace("\\", "-")
    filename = filename.replace("?", "_")
    filename = filename.replace("*", "_")
    filename = filename.replace("<", "_smaller_")
    filename = filename.replace(">", "_greater_")
    filename = filename.replace("|", "-")
    filename = filename.replace('"', "_quote_")
    return filename


def timestamp_to_ISO8601(timestamp):
    """

    Parameters
    ----------
    timestamp :


    Returns
    -------

    """
    if timestamp is None:
        return "None"
    from_stamp = dt.fromtimestamp(timestamp)
    return from_stamp.astimezone().isoformat()


def recourse_entry_dict(entry, metadata):
    """Recoursively makes the metadata to a dictionary.

    Parameters
    ----------
    entry :

    metadata :


    Returns
    -------

    """
    # TODO check if actually necessary
    if not hasattr(metadata, "items"):
        entry.attrs["value"] = metadata
        return
    for key, val in metadata.items():
        if isinstance(val, databroker.core.Start) or isinstance(
            val, databroker.core.Stop
        ):
            val = dict(val)
            stamp = val["time"]
            val["time"] = timestamp_to_ISO8601(stamp)
            # stamp = rundict['metadata_stop']['time']
            # rundict['metadata_stop']['time'] = timestamp_to_ISO8601(stamp)
        if type(val) is dict:
            if key == "start":
                sub_entry = entry
            else:
                sub_entry = entry.create_group(key)
            recourse_entry_dict(sub_entry, val)
        elif type(val) is list:
            no_dict = False
            for i, value in enumerate(val):
                if isinstance(value, dict):
                    sub_entry = entry.create_group(f"{key}_{i}")
                    recourse_entry_dict(sub_entry, value)
                # else:
                #     # entry.attrs[f'{key}_{i}'] = val
                else:
                    no_dict = True
                    break
            if no_dict:
                if any(isinstance(item, str) for item in val):
                    entry[key] = np.array(val).astype("S")
                else:
                    try:
                        entry[key] = val
                    except TypeError:
                        entry[key] = str(val)

        elif val is None:
            continue
        else:
            # entry.attrs[key] = val
            entry[key] = val


def sort_by_list(sort_list, other_lists):
    """

    Parameters
    ----------
    sort_list :

    other_lists :


    Returns
    -------

    """
    s_list = sorted(zip(sort_list, *other_lists), key=lambda x: x[0])
    return zip(*s_list)


def get_param_dict(param_values):
    """

    Parameters
    ----------
    param_values :


    Returns
    -------

    """
    p_s = {}
    for vals in param_values:
        for k in vals:
            if k in p_s:
                p_s[k].append(vals[k].value)
            else:
                p_s[k] = [vals[k].value]
    return p_s


class FileManager:
    """
    Class taken from suitcase-nxsas!

    A class that manages multiple files.

    Parameters
    ----------
    directory : str or Path
        The directory (as a string or as a Path) to create the files inside.
    allowed_modes : Iterable
        Modes accepted by ``MultiFileManager.open``. By default this is
        restricted to "exclusive creation" modes ('x', 'xt', 'xb') which raise
        an error if the file already exists. This choice of defaults is meant
        to protect the user for unintentionally overwriting old files. In
        situations where overwrite ('w', 'wb') or append ('a', 'r+b') are
        needed, they can be added here.
    This design is inspired by Python's zipfile and tarfile libraries.
    """

    def __init__(self, directory, new_file_each=True, file_extension=None):
        self.directory = Path(directory)
        self._reserved_names = set()
        self._artifacts = collections.defaultdict(list)
        self._new_file_each = new_file_each
        self._files = dict()
        self.file_extension = file_extension
        self._last_file_settings = None
        self._files_of_run = []

    @property
    def artifacts(self):
        return dict(self._artifacts)

    def reserve_name(self, entry_name, relative_file_path):
        if Path(relative_file_path).is_absolute():
            raise SuitcaseUtilsValueError(
                f"{relative_file_path!r} must be structured like a relative file path."
            )
        abs_file_path = (
            (self.directory / Path(relative_file_path)).expanduser().resolve()
        )
        i = 1
        while (
            (abs_file_path in self._reserved_names)
            or os.path.isfile(abs_file_path)
            and self._new_file_each
        ):
            if isinstance(abs_file_path, Path):
                abs_file_path = abs_file_path.as_posix()
            if abs_file_path.endswith(f"_{i-1}{self.file_extension}"):
                abs_file_path = abs_file_path.replace(
                    f"_{i - 1}{self.file_extension}", f"_{i}{self.file_extension}"
                )
            else:
                abs_file_path = (
                    os.path.splitext(abs_file_path)[0] + f"_{i}{self.file_extension}"
                )
            i += 1
        self._reserved_names.add(abs_file_path)
        self._artifacts[entry_name].append(abs_file_path)
        return abs_file_path

    def open(self, relative_file_path, entry_name, mode, **open_file_kwargs):
        abs_file_path = self.reserve_name(entry_name, relative_file_path)
        os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
        f = h5py.File(abs_file_path, mode=mode, **open_file_kwargs)
        self._last_file_settings = {
            "name": abs_file_path,
            "mode": mode,
        }
        self._last_file_settings.update(open_file_kwargs)
        self._files[abs_file_path] = f
        return f

    def make_new_file(self):
        """
        Create a new file and return it. This is used to create a new with ongoing data.
        """
        if self._last_file_settings is None:
            raise ValueError(
                "The last file settings are not available. No file was opened before."
            )
        file_settings = self._last_file_settings.copy()
        if isinstance(file_settings["name"], str) and "Xhours" in file_settings["name"]:
            i = int(file_settings["name"].split("_Xhours_")[-1].split(".")[-2])
            file_settings["name"] = file_settings["name"].replace(
                f"_Xhours_{i}.", f"_Xhours_{i+1}."
            )
        else:
            file_settings["name"] = (
                "".join(file_settings["name"].split(".")[:-1])
                + f"_Xhours_1."
                + file_settings["name"].split(".")[-1]
            )
        f = h5py.File(**file_settings)
        self._files_of_run.append(self._last_file_settings)
        self._last_file_settings = file_settings
        self._files[self._last_file_settings["name"]] = f
        return f

    def get_all_run_files(self):
        files = []
        for file in self._files_of_run:
            if file["name"] in self._files:
                files.append(self._files[file["name"]])
            else:
                f = h5py.File(**file)
                self._files[file["name"]] = f
                files.append(f)
        return files

    def get_last_file(self):
        """
        Returns the last file opened by the manager.
        """
        if self._last_file_settings is None:
            raise ValueError(
                "The last file settings are not available. No file was opened before."
            )
        if self._last_file_settings["name"] in self._files:
            return self._files[self._last_file_settings["name"]]
        f = h5py.File(**self._last_file_settings)
        self._files[self._last_file_settings["name"]] = f
        return f

    def close(self):
        """
        close all files opened by the manager
        """
        for filepath, f in self._files.items():
            f.close()
        self._files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exception_details):
        self.close()


class Serializer(event_model.DocumentRouter):
    """
    Serialize a stream of documents to nomad_camels_hdf5.

    .. note::

        This can alternatively be used to write data to generic buffers rather
        than creating files on disk. See the documentation for the
        ``directory`` parameter below.

    Parameters
    ----------
    directory : string, Path, or Manager
        For basic uses, this should be the path to the output directory given
        as a string or Path object. Use an empty string ``''`` to place files
        in the current working directory.

        In advanced applications, this may direct the serialized output to a
        memory buffer, network socket, or other writable buffer. It should be
        an instance of ``suitcase.utils.MemoryBufferManager`` and
        ``suitcase.utils.MultiFileManager`` or any object implementing that
        interface. See the suitcase documentation at
        https://nsls-ii.github.io/suitcase for details.

    file_prefix : str, optional
        The first part of the filename of the generated output files. This
        string may include templates as in ``{proposal_id}-{sample_name}-``,
        which are populated from the RunStart document. The default value is
        ``{uid}-`` which is guaranteed to be present and unique. A more
        descriptive value depends on the application and is therefore left to
        the user.

    **kwargs : kwargs
        Keyword arugments to be passed through to the underlying I/O library.

    Attributes
    ----------
    artifacts
        dict mapping the 'labels' to lists of file names (or, in general,
        whatever resources are produced by the Manager)
    """

    def __init__(
        self,
        directory,
        file_prefix="{uid}-",
        plot_data=None,
        new_file_each=True,
        do_nexus_output=False,
        new_file_hours=0,
        **kwargs,
    ):
        self._kwargs = kwargs
        self._directory = directory
        self._file_prefix = file_prefix
        self._h5_output_file = None
        self._stream_groups = {}
        self._entry = None
        self._data_entry = None
        self._stream_metadata = {}
        self._stream_names = {}
        self._plot_data = plot_data or []
        self._start_time = 0
        self._channel_links = {}
        self._channel_paths = {}
        self._channels_in_streams = {}
        self._stream_counter = []
        self._current_stream = None
        self._channel_metadata = {}
        self._entry_name = ""
        self.do_nexus_output = do_nexus_output
        self._last_event_timestamp = None
        self.new_file_hours = new_file_hours
        self._start_doc = None

        if self.do_nexus_output:
            self.file_extension = ".nxs"
        else:
            self.file_extension = ".h5"

        if isinstance(directory, (str, Path)):
            # The user has given us a filepath; they want files.
            # Set up a MultiFileManager for them.
            directory = Path(directory)
            self._manager = FileManager(
                directory=directory,
                new_file_each=new_file_each,
                file_extension=self.file_extension,
            )
        else:
            # The user has given us their own Manager instance. Use that.
            self._manager = directory

        # Finally, we usually need some state related to stashing file
        # handles/buffers. For a Serializer that only needs *one* file
        # this may be:
        #
        # self._output_file = None
        #
        # For a Serializer that writes a separate file per stream:
        #
        # self._files = {}

    @property
    def artifacts(self):
        # The 'artifacts' are the manager's way to exposing to the user a
        # way to get at the resources that were created. For
        # `MultiFileManager`, the artifacts are filenames.  For
        # `MemoryBuffersManager`, the artifacts are the buffer objects
        # themselves. The Serializer, in turn, exposes that to the user here.
        #
        # This must be a property, not a plain attribute, because the
        # manager's `artifacts` attribute is also a property, and we must
        # access it anew each time to be sure to get the latest contents.
        return self._manager.artifacts

    def close(self):
        """
        Close all of the resources (e.g. files) allocated.
        """
        self._manager.close()

    # These methods enable the Serializer to be used as a context manager:
    #
    # with Serializer(...) as serializer:
    #     ...
    #
    # which always calls close() on exit from the with block.

    def __enter__(self):
        return self

    def __exit__(self, *exception_details):
        self.close()

    # Each of the methods below corresponds to a document type. As
    # documents flow in through Serializer.__call__, the DocumentRouter base
    # class will forward them to the method with the name corresponding to
    # the document's type: RunStart documents go to the 'start' method,
    # etc.
    #
    # In each of these methods:
    #
    # - If needed, obtain a new file/buffer from the manager and stash it
    #   on instance state (self._files, etc.) if you will need it again
    #   later. Example:
    #
    #   filename = f'{self._templated_file_prefix}-primary.csv'
    #   file = self._manager.open('stream_data', filename, 'xt')
    #   self._files['primary'] = file
    #
    #   See the manager documentation below for more about the arguments to open().
    #
    # - Write data into the file, usually something like:
    #
    #   content = my_function(doc)
    #   file.write(content)
    #
    #   or
    #
    #   my_function(doc, file)
    def ensure_open(self, include_channel_links=True, new_hour_file=False):
        # check whether the file is open and if not, open it again
        if new_hour_file:
            self._h5_output_file = self._manager.make_new_file()
            self._make_start_entry(copy.deepcopy(self._start_doc))
            self._recreate_paths(include_channel_links=include_channel_links)
        elif self._h5_output_file is None or not self._h5_output_file or new_hour_file:
            self._h5_output_file = self._manager.get_last_file()
            self._entry = self._h5_output_file[self._entry_name]
            self._recreate_paths(include_channel_links=include_channel_links)
        elif include_channel_links:
            self._recreate_channel_links()

    def _recreate_paths(self, include_channel_links=True):
        self._data_entry = self._entry["data"]
        for stream_name, stream_id in self._stream_names.items():
            if stream_name in self._stream_groups:
                continue
            if stream_name == "primary":
                self._stream_groups[stream_id] = self._data_entry
                continue
            if not stream_name in self._data_entry:
                self._stream_groups[stream_id] = self._data_entry.create_group(
                    stream_name
                )
                self._stream_groups[stream_id].attrs["NX_class"] = "NXcollection"
            else:
                self._stream_groups[stream_id] = self._data_entry[stream_name]
        if include_channel_links:
            self._recreate_channel_links()

    def _recreate_channel_links(self):
        for ch, path in self._channel_paths.items():
            self._channel_links[ch] = self._entry[path]

    def start(self, doc):
        # Fill in the file_prefix with the contents of the RunStart document.
        # As in, '{uid}' -> 'c1790369-e4b2-46c7-a294-7abfa239691a'
        # or 'my-data-from-{plan-name}' -> 'my-data-from-scan'
        super().start(doc)
        # if isinstance(doc, databroker.core.Start):
        doc = dict(doc)  # convert to dict or make a copy
        self._templated_file_prefix = self._file_prefix.format(**doc)
        if self._templated_file_prefix.endswith(self.file_extension):
            relative_path = Path(self._templated_file_prefix)
        else:
            relative_path = Path(f"{self._templated_file_prefix}{self.file_extension}")
        entry_name = "entry"
        if "session_name" in doc and doc["session_name"]:
            entry_name = doc["session_name"]

        self._h5_output_file = self._manager.open(
            entry_name=entry_name, relative_file_path=relative_path, mode="a"
        )
        self._last_file_time = doc["time"]
        entry_name = "CAMELS_" + entry_name
        i = 1
        while entry_name in self._h5_output_file:
            if entry_name.endswith(f"_{i - 1}"):
                entry_name = entry_name.replace(f"_{i - 1}", f"_{i}")
            else:
                entry_name += f"_{i}"
            i += 1
        self._entry_name = entry_name
        self._start_doc = copy.deepcopy(doc)
        self._make_start_entry(doc)

    def _make_start_entry(self, doc):
        start_time = doc["time"]
        start_time = timestamp_to_ISO8601(start_time)
        self._start_time = doc.pop("time")
        self._last_event_timestamp = self._start_time
        self._h5_output_file.attrs["file_type"] = "NOMAD CAMELS"
        self._h5_output_file.attrs["NX_class"] = "NXroot"
        entry = self._h5_output_file.create_group(self._entry_name)
        self._entry = entry
        entry.attrs["NX_class"] = "NXcollection"
        entry.attrs["default"] = "data"
        if "versions" in doc and set(doc["versions"].keys()) == {
            "bluesky",
            "ophyd",
        }:
            doc.pop("versions")
        measurement = entry.create_group("measurement_details")
        measurement["start_time"] = start_time
        if "description" in doc:
            desc = doc.pop("description")
            measurement["protocol_description"] = desc
        if "identifier" in doc:
            ident = doc.pop("identifier")
            measurement["measurement_identifier"] = ident
        if "protocol_json" in doc:
            measurement["protocol_json"] = doc.pop("protocol_json")
        if "plan_name" in doc:
            measurement["plan_name"] = doc.pop("plan_name")
        if "plan_type" in doc:
            measurement["plan_type"] = doc.pop("plan_type")
        if "protocol_overview" in doc:
            measurement["protocol_overview"] = doc.pop("protocol_overview")
        if "python_script" in doc:
            measurement["python_script"] = doc.pop("python_script")
        if "scan_id" in doc:
            measurement["scan_id"] = doc.pop("scan_id")
        if "session_name" in doc:
            measurement["session_name"] = doc.pop("session_name")
        uid = None
        if "uid" in doc:
            uid = doc.pop("uid")
            measurement["uid"] = uid
        if "variables" in doc:
            measurement.create_group("protocol_variables")
            recourse_entry_dict(measurement["protocol_variables"], doc.pop("variables"))
        if "measurement_tags" in doc:
            measurement["measurement_tags"] = doc.pop("measurement_tags")
        if "measurement_description" in doc:
            measurement["measurement_description"] = doc.pop("measurement_description")
        program = entry.create_group("program")
        program["program_name"] = "NOMAD CAMELS"
        program["program_url"] = "https://fau-lap.github.io/NOMAD-CAMELS/"
        # proc["program"].attrs["version"] = "0.1"
        # proc["program"].attrs["program_url"] = "https://github.com/FAU-LAP/NOMAD-CAMELS"
        # version_dict = doc.pop("versions") if "versions" in doc else {}
        # vers_group = proc.create_group("versions")
        py_environment = program.create_group("python_environment")
        py_environment.attrs["python_version"] = sys.version
        for x in importlib.metadata.distributions():
            name = x.metadata["Name"]
            if name not in py_environment.keys():
                if name == "nomad_camels":
                    program["version"] = x.version
                py_environment[x.metadata["Name"]] = x.version
            # except Exception as e:
            #     print(e, x.metadata['Name'])
        # recourse_entry_dict(vers_group, version_dict)
        user = entry.create_group("user")
        user.attrs["NX_class"] = "NXuser"
        user_data = doc.pop("user") if "user" in doc else {}
        if "user_id" in user_data:
            id_group = user.create_group("identifier")
            id_group.attrs["NX_class"] = "NXidentifier"
            id_group["identifier"] = user_data.pop("user_id")
            if "ELN-service" in user_data:
                id_group["service"] = user_data.pop("ELN-service")
            else:
                id_group["service"] = "unknown"
        elif "identifier" in user_data:
            id_group = user.create_group("identifier")
            id_group.attrs["NX_class"] = "NXidentifier"
            id_group["identifier"] = user_data.pop("identifier")
            if "ELN-service" in user_data:
                id_group["service"] = user_data.pop("ELN-service")
            else:
                id_group["service"] = "unknown"
        recourse_entry_dict(user, user_data)
        sample = entry.create_group("sample")
        sample.attrs["NX_class"] = "NXsample"
        sample_data = doc.pop("sample") if "sample" in doc else {}
        if "identifier" in sample_data:
            id_group = sample.create_group("identifier")
            id_group.attrs["NX_class"] = "NXidentifier"
            id_group["identifier"] = sample_data.pop("identifier")
            if "full_identifier" in sample_data:
                id_group["full_identifier"] = sample_data.pop("full_identifier")
            if "ELN-service" in sample_data:
                id_group["service"] = sample_data.pop("ELN-service")
            else:
                id_group["service"] = "unknown"
        recourse_entry_dict(sample, sample_data)

        instr = entry.create_group("instruments")
        # instr.attrs["NX_class"] = "NXinstrument"
        device_data = doc.pop("devices") if "devices" in doc else {}
        for dev, dat in device_data.items():
            dev_group = instr.create_group(dev)
            dev_group.attrs["NX_class"] = "NXinstrument"
            if "instrument_camels_channels" in dat:
                sensor_group = dev_group.create_group("sensors")
                output_group = dev_group.create_group("outputs")
                channel_dict = dat.pop("instrument_camels_channels")
                for ch, ch_dat in channel_dict.items():
                    is_output = ch_dat.pop("output")
                    ch_dat = dict(ch_dat)
                    sensor_name = ch_dat.pop("name").split(".")[-1]
                    if is_output:
                        sensor = output_group.create_group(sensor_name)
                        sensor.attrs["NX_class"] = "NXactuator"
                    else:
                        sensor = sensor_group.create_group(sensor_name)
                        sensor.attrs["NX_class"] = "NXsensor"
                    sensor["name"] = ch

                    metadata = ch_dat.pop("metadata")
                    recourse_entry_dict(sensor, metadata)
                    self._channel_metadata[ch] = metadata
                    recourse_entry_dict(sensor, ch_dat)
                    self._channel_links[ch] = sensor
                    self._channel_paths[ch] = "/".join(
                        [
                            "instruments",
                            dev,
                            "outputs" if is_output else "sensors",
                            sensor_name,
                        ]
                    )
            fab_group = dev_group.create_group("fabrication")
            fab_group.attrs["NX_class"] = "NXfabrication"
            if "idn" in dat:
                fab_group["model"] = dat.pop("idn")
            else:
                fab_group["model"] = dat["device_class_name"]
            dev_group["name"] = dat.pop("device_class_name")
            dev_group["short_name"] = dev
            # settings = dev_group.create_group("settings")
            if "ELN-instrument-id" in dat and dat["ELN-instrument-id"]:
                id_group = fab_group.create_group("identifier")
                id_group.attrs["NX_class"] = "NXidentifier"
                id_group["identifier"] = dat.pop("ELN-instrument-id")
                if "full_identifier" in dat:
                    id_group["full_identifier"] = dat.pop("full_identifier")
                if "ELN-service" in dat:
                    id_group["service"] = dat.pop("ELN-service")
                else:
                    id_group["service"] = "unknown"
            elif "identifier" in dat and dat["identifier"]:
                id_group = fab_group.create_group("identifier")
                id_group.attrs["NX_class"] = "NXidentifier"
                id_group["identifier"] = dat.pop("identifier")
                if "ELN-service" in dat:
                    id_group["service"] = dat.pop("ELN-service")
                else:
                    id_group["service"] = "unknown"
            if "ELN-metadata" in dat:
                recourse_entry_dict(
                    fab_group, {"ELN-metadata": dat.pop("ELN-metadata")}
                )

            used_keys = []
            for key, val in dat.items():
                if key.startswith("python_file_"):
                    if "driver_files" not in dev_group:
                        dev_group.create_group("driver_files")
                        dev_group["driver_files"].attrs["NX_class"] = "NXcollection"
                    dev_group["driver_files"][key] = val
                    used_keys.append(key)
            for key in used_keys:
                dat.pop(key)

            recourse_entry_dict(dev_group, dat)

        recourse_entry_dict(entry, doc)

        self._data_entry = entry.create_group("data")
        self._data_entry.attrs["NX_class"] = "NXcollection"
        if uid is not None:
            doc["uid"] = uid

    def descriptor(self, doc):
        super().descriptor(doc)
        self.ensure_open(include_channel_links=False)
        stream_name = doc["name"]
        stream_name = stream_name.replace("||sub_stream||", "/")
        stream_name = stream_name.replace("||subprotocol_stream||", "/")
        if "_fits_readying_" in stream_name:
            return
        if stream_name in self._stream_groups:
            raise ValueError(f"Stream {stream_name} already exists.")
        if stream_name == "primary":
            stream_group = self._data_entry
        elif stream_name == "_live_metadata_reading_":
            self._stream_groups[doc["uid"]] = stream_name
            return
        else:
            stream_group = self._data_entry.create_group(stream_name)
            stream_group.attrs["NX_class"] = "NXcollection"
        self._stream_groups[doc["uid"]] = stream_group
        self._stream_names[stream_name] = doc["uid"]
        self._stream_metadata[doc["uid"]] = doc["data_keys"]

    def event_page(self, doc):
        # There are other representations of Event data -- 'event' and
        # 'bulk_events' (deprecated). But that does not concern us because
        # DocumentRouter will convert this representations to 'event_page'
        # then route them through here.
        super().event_page(doc)
        # check if events are coming fast, if so, don't close the file after writing, otherwise close it
        if (
            self.new_file_hours
            and doc["time"][0] - self._last_file_time > self.new_file_hours * 3600
        ):
            self._last_file_time = doc["time"][0]
            with self._manager as mgr:
                self.ensure_open(include_channel_links=False, new_hour_file=True)
                self.handle_event_page(doc)
        elif doc["time"][0] - self._last_event_timestamp > 1:
            with self._manager as mgr:
                self.ensure_open(include_channel_links=False)
                self.handle_event_page(doc)
        else:
            self.ensure_open(include_channel_links=False)
            self.handle_event_page(doc)
            self._h5_output_file.flush()  # write buffer to file right away to prevent data loss
        self._last_event_timestamp = doc["time"][0]

    def handle_event_page(self, doc):
        stream_group = self._stream_groups.get(doc["descriptor"], None)
        if stream_group is None:
            return
        elif stream_group == "_live_metadata_reading_":
            # take the single entries from the metadata and write them in the info
            meas_group = self._entry["measurement_details"]
            live_metadata = doc["data"]["live_metadata"][0]
            if hasattr(live_metadata, "_fields"):
                for info in live_metadata._fields:
                    meas_group[info] = live_metadata._asdict()[info]
            elif isinstance(live_metadata, dict):
                for info, value in live_metadata.items():
                    meas_group[info] = value
            return
        if self._current_stream != doc["descriptor"]:
            self._current_stream = doc["descriptor"]
            self._stream_counter.append([doc["descriptor"], 1])
        else:
            self._stream_counter[-1][1] += 1
        if len(doc["time"]) == 1:
            time = np.asarray([doc["time"][0]])
            since = np.asarray([doc["time"][0] - self._start_time])
        else:
            for k in doc["timestamps"]:
                time = np.asarray(doc["timestamps"][k])
                since = time - self._start_time
                break
        if "time" not in stream_group.keys():
            stream_group.create_dataset(
                name="time", data=time, chunks=(1,), maxshape=(None,)
            )
            stream_group.create_dataset(
                name="ElapsedTime", data=since, chunks=(1,), maxshape=(None,)
            )
            stream_group["time"].attrs["units"] = "s"
            stream_group["ElapsedTime"].attrs["units"] = "s"
        else:
            stream_group["time"].resize((stream_group["time"].shape[0] + 1,))
            stream_group["time"][-1] = time
            stream_group["ElapsedTime"].resize(
                (stream_group["ElapsedTime"].shape[0] + 1,)
            )
            stream_group["ElapsedTime"][-1] = since
        for ep_data_key, ep_data_list in doc["data"].items():
            metadata = self._stream_metadata[doc["descriptor"]][ep_data_key]
            if ep_data_key not in self._channels_in_streams:
                self._channels_in_streams[ep_data_key] = [doc["descriptor"]]
            # check if the data is a namedtuple
            if isinstance(ep_data_list[0], tuple) or (
                ep_data_key.endswith("_variable_signal") and "variables" in metadata
            ):
                # check if group already exists
                if ep_data_key not in stream_group.keys():
                    sub_group = stream_group.create_group(ep_data_key)
                else:
                    sub_group = stream_group[ep_data_key]
                # make one dataset for each field in the namedtuple
                if isinstance(ep_data_list[0], tuple):
                    for field in ep_data_list[0]._fields:
                        # get the data for the field
                        field_data = np.asarray([getattr(ep_data_list[0], field)])
                        self._add_data_to_stream_group(
                            metadata, sub_group, field_data, field
                        )
                    continue
                # make one dataset for each variable in the variable signal
                for i, var in enumerate(metadata["variables"]):
                    # get the data for the variable
                    try:
                        var_data = np.asarray([ep_data_list[0][i]])
                    except KeyError:
                        var_data = np.asarray([ep_data_list[0][var]])
                    self._add_data_to_stream_group(metadata, sub_group, var_data, var)
                continue
            ep_data_array = np.asarray(ep_data_list)

            if str(ep_data_array.dtype).startswith("<U"):
                ep_data_array = ep_data_array.astype(bytes)
            self._add_data_to_stream_group(
                metadata, stream_group, ep_data_array, ep_data_key
            )

    def _add_data_to_stream_group(
        self, metadata, stream_group, ep_data_array, ep_data_key
    ):
        if str(ep_data_array.dtype).startswith("<U"):
            ep_data_array = ep_data_array.astype(bytes)
        if ep_data_key not in stream_group.keys():
            if any(dim <= 0 for dim in ep_data_array.shape):
                print(f"Skipping {ep_data_key} because of shape {ep_data_array.shape}")
                return
            stream_group.create_dataset(
                data=ep_data_array,
                name=ep_data_key,
                chunks=(1, *ep_data_array.shape[1:]),
                maxshape=(None, *ep_data_array.shape[1:]),
            )
            for key, val in metadata.items():
                stream_group[ep_data_key].attrs[key] = val
            if ep_data_key in self._channel_metadata:
                for key, val in self._channel_metadata[ep_data_key].items():
                    stream_group[ep_data_key].attrs[key] = val
        else:
            ds = stream_group[ep_data_key]
            ds.resize((ds.shape[0] + ep_data_array.shape[0]), axis=0)
            ds[-ep_data_array.shape[0] :] = ep_data_array

    def get_length_of_stream(self, stream_id):
        if stream_id not in self._stream_groups:
            return 0
        elif "time" not in self._stream_groups[stream_id]:
            return 0
        return len(self._stream_groups[stream_id]["time"])

    def stop(self, doc):
        super().stop(doc)
        with self._manager as mgr:
            self.ensure_open(include_channel_links=True)
            self._make_stop_entry(copy.deepcopy(doc))

        for f in self._manager.get_all_run_files():
            self._h5_output_file = f
            self._entry = f[self._entry_name]
            self._recreate_paths(include_channel_links=True)
            self._make_stop_entry(copy.deepcopy(doc))
            self._h5_output_file.flush()

        self.close()
    

    def _check_single_group(self, group_to_check, search_strings):
        """
        Core logic to find matching datasets within a single group, without recursion.
        This is a helper function for find_dataset_matches_in_group.
        """
        search_set = set(search_strings)
        candidates = {}
        
        def build_path(parent_path, child_name):
            return f"/{child_name}" if parent_path == "/" else f"{parent_path}/{child_name}"

        for child_name in group_to_check.keys():
            if not child_name.endswith("_variable_signal"):
                candidates[child_name] = build_path(group_to_check.name, child_name)

        for child_name in group_to_check.keys():
            if child_name.endswith("_variable_signal"):
                child_obj = group_to_check.get(child_name)
                if isinstance(child_obj, h5py.Group):
                    for grandchild_name in child_obj.keys():
                        grandchild_path = build_path(child_obj.name, grandchild_name)
                        candidates[grandchild_name] = grandchild_path
                    break 
        # A match is valid if the dataset name is in the search string OR vice-versa.
        is_viable = all(any(c_name in s or s in c_name for c_name in candidates) for s in search_set)
        if not is_viable:
            return []

        unmatched_strings = search_set.copy()
        candidate_pool = candidates.copy() 
        resulting_paths = set()

        while unmatched_strings:
            best_candidate_name = None
            strings_covered_by_best = set()
            for c_name in candidate_pool:
                # --- FIX: Check for substring match in BOTH directions ---
                covered = {s for s in unmatched_strings if c_name in s or s in c_name}
                if len(covered) > len(strings_covered_by_best):
                    best_candidate_name = c_name
                    strings_covered_by_best = covered
            
            if not best_candidate_name:
                return []

            resulting_paths.add(candidate_pool[best_candidate_name])
            unmatched_strings -= strings_covered_by_best
            del candidate_pool[best_candidate_name]

        if not unmatched_strings:
            return sorted(list(resulting_paths))
        
        return []

    def find_dataset_matches_in_group(self, start_group, search_strings_a, search_strings_b):
        """
        Finds if a set of datasets exists that collectively contain all specified
        search strings from two lists. It then returns the results as two dictionaries.

        It first checks `start_group`. If no match for the combined list is found,
        it looks for a subgroup "primary" and checks each group inside it.

        Args:
            start_group (h5py.Group): The h5py Group object to search within.
            search_strings_a (list of str): The first list of substrings.
            search_strings_b (list of str): The second list of substrings.

        Returns:
            tuple[dict[str, str], dict[str, str]]: A tuple of two dictionaries.
                - The first maps strings from list A to their found dataset paths.
                - The second maps strings from list B to their found dataset paths.
                Returns ({}, {}) if no complete match is found.
        """
        combined_search_strings = search_strings_a + search_strings_b
        if not combined_search_strings:
            return {}, {}

        def create_result_dicts(all_paths, list_a, list_b):
            """Helper to map search strings to the paths where they were found."""
            dict_a = {}
            dict_b = {}
            
            for search_str in list_a:
                for path in all_paths:
                    dataset_name = path.split('/')[-1]
                    # --- FIX: Check for substring match in BOTH directions ---
                    if dataset_name in search_str or search_str in dataset_name:
                        dict_a[search_str] = path
                        break # Assign the first path that matches
            
            for search_str in list_b:
                for path in all_paths:
                    dataset_name = path.split('/')[-1]
                    # --- FIX: Check for substring match in BOTH directions ---
                    if dataset_name in search_str or search_str in dataset_name:
                        dict_b[search_str] = path
                        break # Assign the first path that matches

            return dict_a, dict_b

        # 1. Check the start_group itself.
        initial_match_paths = self._check_single_group(start_group, combined_search_strings)
        if initial_match_paths:
            return create_result_dicts(initial_match_paths, search_strings_a, search_strings_b)

        # 2. If that fails, look for a fallback "primary" group.
        primary_group = start_group.get("primary")
        if primary_group and isinstance(primary_group, h5py.Group):
            for group_name in sorted(primary_group.keys()):
                sub_group = primary_group.get(group_name)
                if isinstance(sub_group, h5py.Group):
                    sub_group_match_paths = self._check_single_group(sub_group, combined_search_strings)
                    if sub_group_match_paths:
                        return create_result_dicts(sub_group_match_paths, search_strings_a, search_strings_b)

        # 3. If no matches were found.
        return {}, {}

    def _make_stop_entry(self, doc):
        end_time = doc["time"]
        end_time = timestamp_to_ISO8601(end_time)
        self._entry["measurement_details"]["end_time"] = end_time

        for ch, stream_docs in self._channels_in_streams.items():
            if ch not in self._channel_links:
                continue
            total_length = 0
            sources = {}
            sources_time = {}
            dataset = None
            for stream in stream_docs:
                total_length += self.get_length_of_stream(stream)
                if not ch in self._stream_groups[stream]:
                    continue
                dataset = self._stream_groups[stream][ch]
                sources[stream] = h5py.VirtualSource(self._stream_groups[stream][ch])
                sources_time[stream] = h5py.VirtualSource(
                    self._stream_groups[stream]["time"]
                )
                dtype_time = self._stream_groups[stream]["time"].dtype
            if dataset is None:
                continue
            shape = (total_length, *dataset.shape[1:])
            layout = h5py.VirtualLayout(shape=shape, dtype=dataset.dtype)
            layout_time = h5py.VirtualLayout(shape=(total_length,), dtype=dtype_time)
            n = 0
            counts_per_stream = {}
            for stream, count in self._stream_counter:
                if stream not in stream_docs:
                    continue
                if stream not in counts_per_stream:
                    counts_per_stream[stream] = 0
                    n_stream = 0
                else:
                    n_stream = counts_per_stream[stream]
                layout[n : n + count] = sources[stream][n_stream : n_stream + count]
                layout_time[n : n + count] = sources_time[stream][
                    n_stream : n_stream + count
                ]
                n += count
                counts_per_stream[stream] += count
            self._channel_links[ch].create_virtual_dataset("value_log", layout)
            self._channel_links[ch].create_virtual_dataset("timestamps", layout_time)

        
        for plot_index, plot in enumerate(self._plot_data):
            full_namespace_list = list(plot.eva.namespace.keys())
            cut_off_index = full_namespace_list.index("StartTime")
            available_channel_names = full_namespace_list[cut_off_index :] # this could be changed to self._channel_names + the variables somehow
            # Replace the keys of the plot.y_axes dict with the evaluated aliases
            stream_axes = {}
            stream_signals = {}
            if (
                plot.stream_name in self._stream_names
                or plot.stream_name.replace("||sub_stream||", "/") in self._stream_names or plot.stream_name.replace("||subprotocol_stream||", "/") in self._stream_names or plot.stream_name.replace("||sub_stream||", "/").replace("||subprotocol_stream||", "/") in self._stream_names
            ) and hasattr(plot, "x_name"):
                stream_name = plot.stream_name
                if stream_name not in self._stream_names:
                    stream_name = stream_name.replace("||sub_stream||", "/")
                    stream_name = stream_name.replace("||subprotocol_stream||", "/")
                if stream_name not in stream_axes:
                    stream_axes[stream_name] = []
                    stream_signals[stream_name] = []
                axes = stream_axes[stream_name]
                signals = stream_signals[stream_name]
                group = self._stream_groups[self._stream_names[stream_name]]
                # Resolve aliases in plot.x_name
                plot.x_name = plot.eva.exchange_aliases(plot.x_name)
                individual_variables_from_x_name = get_variables_from_expression(plot.x_name)
                if individual_variables_from_x_name:
                    for var in individual_variables_from_x_name:
                        if var in available_channel_names:
                            axes.append(var)
                if hasattr(plot, "z_name"):
                    plot_type = "2D"
                    # Resolve aliases in plot.y_name
                    plot.y_name = plot.eva.exchange_aliases(plot.y_name)
                    individual_variables_from_y_name = get_variables_from_expression(plot.y_name)
                    if individual_variables_from_y_name:
                        for var in individual_variables_from_y_name:
                            if var in available_channel_names:
                                axes.append(var)
                    # Resolve aliases in plot.z_name
                    plot.z_name = plot.eva.exchange_aliases(plot.z_name)
                    individual_variables_from_z_name = get_variables_from_expression(plot.z_name)
                    if individual_variables_from_z_name:
                        for var in individual_variables_from_z_name:
                            if var in available_channel_names:
                                signals.append(var)
                else:
                    for key in list(plot.y_axes.keys()):
                        new_key = plot.eva.exchange_aliases(key)
                        if new_key != key:
                            plot.y_axes[new_key] = plot.y_axes.pop(key)
                    plot_type = "1D"
                    # Resolve all the aliases in y_names
                    for i, y in enumerate(plot.y_names):
                        plot.y_names[i] = plot.eva.exchange_aliases(y)
                    for y in plot.y_names:
                        individual_variables_from_y_name = get_variables_from_expression(y)
                        if individual_variables_from_y_name:
                            for var in individual_variables_from_y_name:
                                if var in available_channel_names:
                                    signals.append(var)
                check_result = self.find_dataset_matches_in_group(group, axes, signals)
                if not check_result:
                    continue
                rel_axes, rel_signals = check_result
                plot_group = group.create_group(f"plot_{plot_index+1}")
                plot_group.attrs["NX_class"] = "NXdata"
                group.attrs["default"] = f"plot_{plot_index+1}"
                if plot_type == "1D":
                    if plot.x_name in rel_axes:
                        plot_group["_plot_data_axes"] = h5py.SoftLink(rel_axes[plot.x_name])
                        plot_group["_plot_data_axes"].attrs["long_name"] = plot.x_name
                    elif any(key in plot.x_name for key in rel_axes.keys()):
                        print("Axes name and dataset name do not match, likely due to arithmetic operation. Evaluating the axes expression")
                        import numexpr as ne
                        data_context = {}
                        for key, path_val in rel_axes.items():
                            last_path_element = path_val.split("/")[-1]
                            data_context[last_path_element] = self._h5_output_file[path_val][()]
                        cleaned_x = plot.x_name.replace("np.","") # remove np. to make it compatible with numexpr
                        evaluated_data = ne.evaluate(cleaned_x, local_dict=data_context)
                        plot_group["_plot_data_axes"] = evaluated_data
                        plot_group["_plot_data_axes"].attrs["long_name"] = plot.x_name
                    else:
                        print(f"The x data {plot.x_name} you want to plot could not be found in the data file.\nMake sure you actually read this data in your protocol.")
                    y_count = 0
                    for y in plot.y_names:
                        if y_count == 0:
                            if y in rel_signals:
                                plot_group["_plot_data_signal"] = h5py.SoftLink(rel_signals[y])
                                plot_group["_plot_data_signal"].attrs["long_name"] = y
                                plot_group["_plot_data_signal"].attrs["y_axes_index"] = plot.y_axes[plot.eva.exchange_aliases(y)]
                            elif any(key in y for key in rel_signals.keys()):
                                print("Signal name and dataset name do not match, likely due to arithmetic operation. Evaluating the signal expression")
                                import numexpr as ne
                                data_context = {}
                                for key, path_val in rel_signals.items():
                                    last_path_element = path_val.split("/")[-1]
                                    data_context[last_path_element] = self._h5_output_file[path_val][()]
                                cleaned_y = y.replace("np.","") # remove np. to make it compatible with numexpr
                                evaluated_data = ne.evaluate(cleaned_y, local_dict=data_context)
                                plot_group["_plot_data_signal"] = evaluated_data
                                plot_group["_plot_data_signal"].attrs["long_name"] = y
                                plot_group["_plot_data_signal"].attrs["y_axes_index"] = plot.y_axes[plot.eva.exchange_aliases(y)]
                            else:
                                print(f"The y data {y} you want to plot could not be found in the data file.\nMake sure you actually read this data in your protocol.")
                        else:
                            if y in rel_signals:
                                plot_group[f"_plot_data_signal_{y_count}"] = h5py.SoftLink(rel_signals[y])
                                plot_group[f"_plot_data_signal_{y_count}"].attrs["long_name"] = y
                                plot_group[f"_plot_data_signal_{y_count}"].attrs["y_axes_index"] = plot.y_axes[plot.eva.exchange_aliases(y)]
                            elif any(key in y for key in rel_signals.keys()):
                                print("y data name and dataset name do not match, likely due to arithmetic operation. Evaluating the signal expression")
                                import numexpr as ne
                                data_context = {}
                                for key, path_val in rel_signals.items():
                                    last_path_element = path_val.split("/")[-1]
                                    data_context[last_path_element] = self._h5_output_file[path_val][()]
                                cleaned_y = y.replace("np.","") # remove np. to make it compatible with numexpr
                                evaluated_data = ne.evaluate(cleaned_y, local_dict=data_context)
                                plot_group[f"_plot_data_signal_{y_count}"] = evaluated_data
                                plot_group[f"_plot_data_signal_{y_count}"].attrs["long_name"] = y
                                plot_group[f"_plot_data_signal_{y_count}"].attrs["y_axes_index"] = plot.y_axes[plot.eva.exchange_aliases(y)]
                            else:
                                print(f"The y data {y} you want to plot could not be found in the data file.\nMake sure you actually read this data in your protocol.")
                        y_count += 1
                    plot_group.attrs["axes"] = "_plot_data_axes"
                    plot_group.attrs["signal"] = "_plot_data_signal"
                    # Add a list of auxiliary signals if there are more than one y data
                    if y_count > 1:
                        aux_signals = []
                        for i in range(1, y_count):
                            aux_signals.append(f"_plot_data_signal_{i}")
                        plot_group.attrs["auxiliary_signals"] = aux_signals
                    
                elif plot_type == "2D":
                    if plot.x_name in rel_axes:
                        plot_group["_plot_data_axes_0"] = h5py.SoftLink(rel_axes[plot.x_name])
                        plot_group["_plot_data_axes_0"].attrs["long_name"] = plot.x_name
                    elif any(key in plot.x_name for key in rel_axes.keys()):
                        print("X Axes name and dataset name do not match, likely due to arithmetic operation. Evaluating the axes expression")
                        import numexpr as ne
                        data_context = {}
                        for key, path_val in rel_axes.items():
                            last_path_element = path_val.split("/")[-1]
                            data_context[last_path_element] = self._h5_output_file[path_val][()]
                        cleaned_x = plot.x_name.replace("np.","") # remove np. to make it compatible with numexpr
                        evaluated_data = ne.evaluate(cleaned_x, local_dict=data_context)
                        plot_group["_plot_data_axes_0"] = evaluated_data
                        plot_group["_plot_data_axes_0"].attrs["long_name"] = plot.x_name
                    else:
                        print(f"The x data {plot.x_name} you want to plot could not be found in the data file.\nMake sure you actually read this data in your protocol.")
                    if plot.y_name in rel_axes:
                        plot_group["_plot_data_axes_1"] = h5py.SoftLink(rel_axes[plot.y_name])
                        plot_group["_plot_data_axes_1"].attrs["long_name"] = plot.y_name
                    elif any(key in plot.y_name for key in rel_axes.keys()):
                        print("Y Axes name and dataset name do not match, likely due to arithmetic operation. Evaluating the axes expression")
                        import numexpr as ne
                        data_context = {}
                        for key, path_val in rel_axes.items():
                            last_path_element = path_val.split("/")[-1]
                            data_context[last_path_element] = self._h5_output_file[path_val][()]
                        cleaned_y = plot.y_name.replace("np.","") # remove np. to make it compatible with numexpr
                        evaluated_data = ne.evaluate(cleaned_y, local_dict=data_context)
                        plot_group["_plot_data_axes_1"] = evaluated_data
                        plot_group["_plot_data_axes_1"].attrs["long_name"] = plot.y_name
                    else:
                        print(f"The y data {plot.y_name} you want to plot could not be found in the data file.\nMake sure you actually read this data in your protocol.")
                    if plot.z_name in rel_signals:
                        plot_group["_plot_data_signal"] = h5py.SoftLink(rel_signals[plot.z_name])
                        plot_group["_plot_data_signal"].attrs["long_name"] = plot.z_name
                    elif any(key in plot.z_name for key in rel_signals.keys()):
                        print("Signal name and dataset name do not match, likely due to arithmetic operation. Evaluating the signal expression")
                        import numexpr as ne
                        data_context = {}
                        for key, path_val in rel_signals.items():
                            last_path_element = path_val.split("/")[-1]
                            data_context[last_path_element] = self._h5_output_file[path_val][()]
                        cleaned_z = plot.z_name.replace("np.","") # remove np. to make it compatible with numexpr
                        evaluated_data = ne.evaluate(cleaned_z, local_dict=data_context)
                        plot_group["_plot_data_signal"] = evaluated_data
                        plot_group["_plot_data_signal"].attrs["long_name"] = plot.z_name
                    else:
                        print(f"The z data {plot.z_name} you want to plot could not be found in the data file.\nMake sure you actually read this data in your protocol.")
                    plot_group.attrs["axes"] = ["_plot_data_axes_0", "_plot_data_axes_1"]
                    plot_group.attrs["signal"] = "_plot_data_signal"
            
            if not hasattr(plot, "liveFits") or not plot.liveFits:
                continue                        
            fit_group = plot_group.require_group("fit")
            for fit_index, fit in enumerate(plot.liveFits):
                if not fit.results:
                    continue
                fg = fit_group.require_group(fit.name)
                param_names = []
                param_values = []
                covars = []
                timestamps = []
                for t, res in fit.results.items():
                    timestamps.append(float(t))
                    if res.covar is None:
                        covar = np.ones(
                            (len(res.best_values), len(res.best_values))
                        )
                        covar *= np.nan
                    else:
                        covar = res.covar
                    covars.append(covar)
                    if not param_names:
                        param_names = res.model.param_names
                    param_values.append(res.params)
                fg.attrs["param_names"] = param_names
                timestamps, covars, param_values = sort_by_list(
                    timestamps, [covars, param_values]
                )
                # isos = []
                # for t in timestamps:
                #     isos.append(timestamp_to_ISO8601(t))
                fg["time"] = timestamps
                since = np.array(timestamps)
                since -= self._start_time
                fg["ElapsedTime"] = since
                fg["covariance"] = covars
                fg["covariance"].attrs["parameters"] = param_names[: len(covars[0])]
                param_values = get_param_dict(param_values)
                for p, v in param_values.items():
                    fg[p] = v
                fg.attrs["y_axes_index"] = plot.y_axes[fit.y]
                fg.attrs["plot_metadata"] = json.dumps(plot.fits[fit_index])

        if self.do_nexus_output:
            self.make_nexus_structure()
        else:
            self._h5_output_file.attrs["default"] = self._entry_name
        nxcollection_default_class(self._h5_output_file)
        self._h5_output_file.attrs["h5py_version"] = h5py.__version__
        self._h5_output_file.attrs["HDF5_Version"] = h5py.version.hdf5_version
        self._h5_output_file.attrs["file_time"] = timestamp_to_ISO8601(self._start_time)

        self.close()

    def make_nexus_structure(self):
        if self._entry_name.startswith("CAMELS_"):
            nexus_name = "NeXus_" + self._entry_name[7:]
        else:
            nexus_name = "NeXus_" + self._entry_name
        self._h5_output_file.attrs["default"] = nexus_name
        nx_group = self._h5_output_file.create_group(nexus_name)
        nx_group.attrs["NX_class"] = "NXentry"
        nx_group.attrs["default"] = "data"
        nx_group["definition"] = "NXsensor_scan"
        nx_group["definition"].attrs["version"] = ""
        nx_group["experiment_description"] = h5py.SoftLink(
            f"/{self._entry_name}/measurement_details/measurement_description"
        )
        nx_group["start_time"] = h5py.SoftLink(
            f"/{self._entry_name}/measurement_details/start_time"
        )
        nx_group["end_time"] = h5py.SoftLink(
            f"/{self._entry_name}/measurement_details/end_time"
        )
        process = nx_group.create_group("process")
        process.attrs["NX_class"] = "NXprocess"
        self._h5_output_file.copy(
            f"/{self._entry_name}/program/program_name",
            f"/{nexus_name}/process/program",
        )
        try:
            version = self._entry["program"]["version"]
        except (KeyError, TypeError):
            version = ""
        try:
            program_url = self._entry["program"]["program_url"]
        except (KeyError, TypeError):
            program_url = ""
        process["program"].attrs["version"] = version
        process["program"].attrs["program_url"] = program_url
        process.create_group("python_environment")
        process["python_environment"].attrs["NX_class"] = "NXparamerters"
        for package in self._entry["program"]["python_environment"]:
            process["python_environment"][package] = h5py.SoftLink(
                f"/{self._entry_name}/program/python_environment/{package}"
            )
        process.create_group("python")
        process["python"].attrs["NX_class"] = "NXparamerters"
        process["python"]["python_version"] = self._entry["program"][
            "python_environment"
        ].attrs["python_version"]
        # additional fields may be added to user and sample of nexus entry, so adding links by element, not to the whole group
        user = nx_group.create_group("user")
        user.attrs["NX_class"] = "NXuser"
        for field in self._entry["user"]:
            if field == "identifier":
                self._h5_output_file.copy(
                    f"/{self._entry_name}/user/identifier/identifier",
                    f"/{nexus_name}/user/identifier_user",
                )
                try:
                    service = self._entry["user"]["identifier"]["service"]
                except (KeyError, TypeError):
                    service = ""
                user["identifier_user"].attrs["type"] = service
                user["identifier_user"].attrs["custom"] = True
            else:
                user[field] = h5py.SoftLink(f"/{self._entry_name}/user/{field}")
        sample = nx_group.create_group("sample")
        sample.attrs["NX_class"] = "NXsample"
        # sample["chemical_formula"] = "SiO2"       #test
        for field in self._entry["sample"]:
            if field == "sample_id":
                if self._entry["sample"]["sample_id"][()]:
                    self._h5_output_file.copy(
                        f"/{self._entry_name}/sample/sample_id",
                        f"/{nexus_name}/sample/identifier_sample",
                    )
                    sample["identifier_sample"].attrs["type"] = "laboratory specific"
                    sample["identifier_sample"].attrs["custom"] = True
            else:
                sample[field] = h5py.SoftLink(f"/{self._entry_name}/sample/{field}")
        for dev in self._entry["instruments"]:
            instrument = nx_group.create_group(dev)
            instrument.attrs["NX_class"] = "NXinstrument"
            environment = instrument.create_group("environment")
            environment.attrs["NX_class"] = "NXenvironment"
            sensors_list = []
            outputs_list = []
            for child in self._entry["instruments"][dev]:
                if child == "ELN-instrument-id":
                    if self._entry["instruments"][dev]["ELN-instrument-id"][()]:
                        self._h5_output_file.copy(
                            f"/{self._entry_name}/instruments/{dev}/ELN-instrument-id",
                            f"/{nexus_name}/{dev}/identifier_ELN_instrument",
                        )
                        instrument["identifier_ELN_instrument"].attrs[
                            "type"
                        ] = "laboratory specific"
                        instrument["identifier_ELN_instrument"].attrs["custom"] = True
                elif child == "name":
                    self._h5_output_file.copy(
                        f"/{self._entry_name}/instruments/{dev}/name",
                        f"/{nexus_name}/{dev}/name",
                    )
                    try:
                        short_name = self._entry["instruments"][dev]["short_name"]
                    except (KeyError, TypeError):
                        short_name = ""
                    instrument["name"].attrs["short_name"] = short_name
                elif child == "short_name":
                    pass
                elif child == "settings":
                    settings = instrument.create_group("settings")
                    settings.attrs["NX_class"] = "NXparameters"
                    for field in self._entry["instruments"][dev]["settings"]:
                        settings[field] = h5py.SoftLink(
                            f"/{self._entry_name}/instruments/{dev}/settings/{field}"
                        )
                elif child == "config_channel_metadata":
                    configs = instrument.create_group("config_channel_metadata")
                    configs.attrs["NX_class"] = "NXparameters"
                    for field in self._entry["instruments"][dev][
                        "config_channel_metadata"
                    ]:
                        configs[field] = h5py.SoftLink(
                            f"/{self._entry_name}/instruments/{dev}/config_channel_metadata/{field}"
                        )
                elif child == "sensors":
                    for sensor_name in self._entry["instruments"][dev]["sensors"]:
                        instrument[sensor_name] = h5py.SoftLink(
                            f"/{self._entry_name}/instruments/{dev}/sensors/{sensor_name}"
                        )
                        environment.create_group(sensor_name)
                        environment[sensor_name].attrs["NX_class"] = "NXsensor"
                        for sensor_child in self._entry["instruments"][dev]["sensors"][
                            sensor_name
                        ]:
                            environment[sensor_name][sensor_child] = h5py.SoftLink(
                                f"/{self._entry_name}/instruments/{dev}/sensors/{sensor_name}/{sensor_child}"
                            )
                        environment[sensor_name][
                            "calibration_time"
                        ] = "1970-01-01T01:00:00+01:00"  # has to be NX_DATE_TIME, not really known
                        environment[sensor_name]["run_control"] = ""
                        environment[sensor_name]["run_control"].attrs[
                            "description"
                        ] = ""
                        environment[sensor_name]["value"] = 0.0
                        sensors_list.append(sensor_name)
                elif child == "outputs":
                    for output_name in self._entry["instruments"][dev]["outputs"]:
                        instrument[output_name] = h5py.SoftLink(
                            f"/{self._entry_name}/instruments/{dev}/outputs/{output_name}"
                        )
                        environment[output_name] = h5py.SoftLink(
                            f"/{self._entry_name}/instruments/{dev}/outputs/{output_name}"
                        )
                        outputs_list.append(output_name)
                else:
                    instrument[child] = h5py.SoftLink(
                        f"/{self._entry_name}/instruments/{dev}/{child}"
                    )
            environment["independent_controllers"] = " ".join(outputs_list)
            environment["measurement_sensors"] = " ".join(sensors_list)
        self.data_to_flat_structure(
            nexus_name=nexus_name, group_name="data", group_path="data"
        )
        nx_group["additional_information"] = h5py.SoftLink(
            f"/{self._entry_name}/measurement_details"
        )
        protocol = nx_group.create_group("protocol")
        protocol.attrs["NX_class"] = "NXnote"
        protocol["file_name"] = h5py.SoftLink(
            f"/{self._entry_name}/measurement_details/plan_name"
        )
        protocol["description"] = h5py.SoftLink(
            f"/{self._entry_name}/measurement_details/protocol_overview"
        )
        self._h5_output_file.attrs["default"] = nexus_name
        nx_group.attrs["default"] = "data"

    def data_to_flat_structure(self, nexus_name, group_name, group_path):
        # copy group and its attributes, but not datasets and not subgroups
        self._h5_output_file[nexus_name].create_group(group_name)
        for key, value in self._entry[group_path].attrs.items():
            self._h5_output_file[nexus_name][group_name].attrs[key] = value
        # softlink all datasets, but not subgroups; recursively call this function for subgroups
        for child in self._entry[group_path]:
            if isinstance(self._entry[group_path][child], h5py.Group):
                self.data_to_flat_structure(
                    nexus_name=nexus_name,
                    group_name=group_name + "_" + child,
                    group_path=f"{group_path}/{child}",
                )
            else:
                self._h5_output_file[nexus_name][group_name][child] = h5py.SoftLink(
                    f"/{self._entry_name}/{group_path}/{child}"
                )


def nxcollection_default_class(group):
    for key in group:
        if isinstance(group[key], h5py.Group):
            if "NX_class" not in group[key].attrs:
                group[key].attrs["NX_class"] = "NXcollection"
            nxcollection_default_class(group[key])
