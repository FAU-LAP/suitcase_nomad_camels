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

__version__ = get_versions()["version"]
del get_versions


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

    Include the experiment's start time formatted as YYYY-MM-DD_HH-MM.

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

    def __init__(self, directory, new_file_each=True):
        self.directory = Path(directory)
        self._reserved_names = set()
        self._artifacts = collections.defaultdict(list)
        self._new_file_each = new_file_each
        self._files = dict()

    @property
    def artifacts(self):
        return dict(self._artifacts)

    def reserve_name(self, entry_name, relative_file_path):
        if Path(relative_file_path).is_absolute():
            raise SuitcaseUtilsValueError(
                f"{relative_file_path!r} must be structured like a relative "
                f"file path."
            )
        abs_file_path = (
            (self.directory / Path(relative_file_path)).expanduser().resolve()
        )
        if (
            (abs_file_path in self._reserved_names)
            or os.path.isfile(abs_file_path.as_posix())
            and self._new_file_each
        ):
            entry_name_non_iso = clean_filename(entry_name)
            abs_file_path = abs_file_path.as_posix()
            abs_file_path = (
                os.path.splitext(abs_file_path)[0] + f"_{entry_name_non_iso}.nxs"
            )
        self._reserved_names.add(abs_file_path)
        self._artifacts[entry_name].append(abs_file_path)
        return abs_file_path

    def open(self, relative_file_path, entry_name, mode, **open_file_kwargs):
        abs_file_path = self.reserve_name(entry_name, relative_file_path)
        os.makedirs(os.path.dirname(abs_file_path), exist_ok=True)
        f = h5py.File(abs_file_path, mode=mode, **open_file_kwargs)
        self._files[abs_file_path] = f
        return f

    def close(self):
        """
        close all files opened by the manager
        """
        for filepath, f in self._files.items():
            f.close()


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
        self._channels_in_streams = {}
        self._stream_counter = []
        self._current_stream = None
        self._channel_metadata = {}

        if isinstance(directory, (str, Path)):
            # The user has given us a filepath; they want files.
            # Set up a MultiFileManager for them.
            directory = Path(directory)
            self._manager = FileManager(
                directory=directory, new_file_each=new_file_each
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

    def start(self, doc):
        # Fill in the file_prefix with the contents of the RunStart document.
        # As in, '{uid}' -> 'c1790369-e4b2-46c7-a294-7abfa239691a'
        # or 'my-data-from-{plan-name}' -> 'my-data-from-scan'
        super().start(doc)
        if isinstance(doc, databroker.core.Start):
            doc = dict(doc)
        self._templated_file_prefix = self._file_prefix.format(**doc)
        if self._templated_file_prefix.endswith(".nxs"):
            relative_path = Path(self._templated_file_prefix)
        else:
            relative_path = Path(f"{self._templated_file_prefix}.nxs")
        entry_name = ""
        if "session_name" in doc:
            entry_name = doc["session_name"] + "_"
        start_time = doc["time"]
        start_time = timestamp_to_ISO8601(start_time)
        self._start_time = doc["time"]
        entry_name += start_time

        self._h5_output_file = self._manager.open(
            entry_name=entry_name, relative_file_path=relative_path, mode="a"
        )
        entry = self._h5_output_file.create_group(entry_name)
        self._entry = entry
        entry.attrs["NX_class"] = "NXentry"
        entry["definition"] = "NXsensor_scan"
        entry["start_time"] = start_time
        if "description" in doc:
            desc = doc.pop("description")
            entry["experiment_description"] = desc
        if "identifier" in doc:
            ident = doc.pop("identifier")
            entry["experiment_identifier"] = ident
        proc = entry.create_group("process")
        proc.attrs["NX_class"] = "NXprocess"
        proc["program"] = "NOMAD CAMELS"
        proc["program"].attrs["version"] = "0.1"
        proc["program"].attrs["program_url"] = "https://github.com/FAU-LAP/NOMAD-CAMELS"
        version_dict = doc.pop("versions") if "versions" in doc else {}
        vers_group = proc.create_group("versions")
        py_environment = proc.create_group("python_environment")
        py_environment.attrs["python_version"] = sys.version
        for x in importlib.metadata.distributions():
            name = x.metadata["Name"]
            if name not in py_environment.keys():
                py_environment[x.metadata["Name"]] = x.version
            # except Exception as e:
            #     print(e, x.metadata['Name'])
        recourse_entry_dict(vers_group, version_dict)
        user = entry.create_group("user")
        user.attrs["NX_class"] = "NXuser"
        user_data = doc.pop("user") if "user" in doc else {}
        recourse_entry_dict(user, user_data)
        sample = entry.create_group("sample")
        sample.attrs["NX_class"] = "NXsample"
        sample_data = doc.pop("sample") if "sample" in doc else {}
        recourse_entry_dict(sample, sample_data)

        instr = entry.create_group("instrument")
        instr.attrs["NX_class"] = "NXinstrument"
        device_data = doc.pop("devices") if "devices" in doc else {}
        for dev, dat in device_data.items():
            dev_group = instr.create_group(dev)
            dev_group.attrs["NX_class"] = "NXfabrication"
            if "idn" in dat:
                dev_group["model"] = dat.pop("idn")
            else:
                dev_group["model"] = dat["device_class_name"]
            if "instrument_camels_channels" in dat:
                sensor_group = dev_group.create_group("sensors")
                for ch, ch_dat in dat["instrument_camels_channels"].items():
                    ch_dat = dict(ch_dat)
                    sensor = sensor_group.create_group(
                        ch_dat.pop("name").split(".")[-1]
                    )
                    sensor.attrs["NX_class"] = "NXsensor"
                    sensor["name"] = ch
                    sensor["is_output"] = ch_dat.pop("output")

                    metadata = ch_dat.pop("metadata")
                    recourse_entry_dict(sensor, metadata)
                    self._channel_metadata[ch] = metadata
                    recourse_entry_dict(sensor, ch_dat)
                    self._channel_links[ch] = sensor
            dev_group["name"] = dat.pop("device_class_name")
            dev_group["short_name"] = dev
            settings = dev_group.create_group("settings")
            recourse_entry_dict(settings, dat)

        recourse_entry_dict(entry, doc)

        self._data_entry = entry.create_group("data")
        self._data_entry.attrs["NX_class"] = "NXdata"

    def descriptor(self, doc):
        super().descriptor(doc)
        stream_name = doc["name"]
        if "_fits_readying_" in stream_name:
            return
        if stream_name in self._stream_groups:
            raise ValueError(f"Stream {stream_name} already exists.")
        if stream_name == "primary":
            stream_group = self._data_entry
        else:
            stream_group = self._data_entry.create_group(stream_name)
            stream_group.attrs["NX_class"] = "NXdata"
        self._stream_groups[doc["uid"]] = stream_group
        self._stream_names[stream_name] = doc["uid"]
        self._stream_metadata[doc["uid"]] = doc["data_keys"]

    def event_page(self, doc):
        # There are other representations of Event data -- 'event' and
        # 'bulk_events' (deprecated). But that does not concern us because
        # DocumentRouter will convert this representations to 'event_page'
        # then route them through here.
        super().event_page(doc)
        stream_group = self._stream_groups.get(doc["descriptor"], None)
        if stream_group is None:
            return
        if self._current_stream != doc["descriptor"]:
            self._current_stream = doc["descriptor"]
            self._stream_counter.append([doc["descriptor"], 1])
        else:
            self._stream_counter[-1][1] += 1
        self._stream_counter
        time = np.asarray([timestamp_to_ISO8601(doc["time"][0])])
        since = np.asarray([doc["time"][0] - self._start_time])
        if "time" not in stream_group.keys():
            stream_group.create_dataset(
                name="time", data=time.astype(bytes), chunks=(1,), maxshape=(None,)
            )
            stream_group.create_dataset(
                name="time_since_start", data=since, chunks=(1,), maxshape=(None,)
            )
        else:
            stream_group["time"].resize((stream_group["time"].shape[0] + 1,))
            stream_group["time"][-1] = time.astype(bytes)
            stream_group["time_since_start"].resize(
                (stream_group["time_since_start"].shape[0] + 1,)
            )
            stream_group["time_since_start"][-1] = since
        for ep_data_key, ep_data_list in doc["data"].items():
            metadata = self._stream_metadata[doc["descriptor"]][ep_data_key]
            if ep_data_key in self._channels_in_streams:
                self._channels_in_streams[ep_data_key].append(doc["descriptor"])
            else:
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
                    var_data = np.asarray([ep_data_list[0][i]])
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
        if ep_data_key not in stream_group.keys():
            if any(dim <= 0 for dim in ep_data_array.shape):
                print(f"Skipping {ep_data_key} because of shape {ep_data_array.shape}")
                return
            if str(ep_data_array.dtype).startswith("<U"):
                ep_data_array = ep_data_array.astype(bytes)
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
        return len(self._stream_groups[stream_id]["time"])

    def stop(self, doc):
        super().stop(doc)
        end_time = doc["time"]
        end_time = timestamp_to_ISO8601(end_time)
        self._entry["end_time"] = end_time

        for ch, stream_docs in self._channels_in_streams.items():
            if ch not in self._channel_links:
                continue
            total_length = 0
            sources = {}
            sources_time = {}
            dataset = None
            for stream in stream_docs:
                total_length += self.get_length_of_stream(stream)
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

        stream_axes = {}
        stream_signals = {}
        for plot in self._plot_data:
            if plot.stream_name in self._stream_names and hasattr(plot, "x_name"):
                if plot.stream_name not in stream_axes:
                    stream_axes[plot.stream_name] = []
                    stream_signals[plot.stream_name] = []
                axes = stream_axes[plot.stream_name]
                signals = stream_signals[plot.stream_name]
                group = self._stream_groups[self._stream_names[plot.stream_name]]
                if plot.x_name not in axes:
                    axes.append(plot.x_name)
                if hasattr(plot, "z_name"):
                    if plot.y_name not in axes:
                        axes.append(plot.y_name)
                    if plot.z_name not in signals:
                        signals.append(plot.z_name)
                else:
                    for y in plot.y_names:
                        if y not in signals:
                            signals.append(y)
                if not hasattr(plot, "liveFits") or not plot.liveFits:
                    continue
                fit_group = group.require_group("fits")
                for fit in plot.liveFits:
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
                    isos = []
                    for t in timestamps:
                        isos.append(timestamp_to_ISO8601(t))
                    fg["time"] = isos
                    since = np.array(timestamps)
                    since -= self._start_time
                    fg["time_since_start"] = since
                    fg["covariance"] = covars
                    fg["covariance"].attrs["parameters"] = param_names[: len(covars[0])]
                    param_values = get_param_dict(param_values)
                    for p, v in param_values.items():
                        fg[p] = v
                    for name, val in fit.additional_data.items():
                        fg[name] = val
        for stream, axes in stream_axes.items():
            signals = stream_signals[stream]
            group = self._stream_groups[self._stream_names[stream]]
            group.attrs["axes"] = axes
            if signals:
                group.attrs["signal"] = signals[0]
                if len(signals) > 1:
                    group.attrs["auxiliary_signals"] = signals[1:]

        self.close()
