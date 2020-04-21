import collections
import logging
import os

from copy import deepcopy
from itertools import chain

from dvc import dependency, output
from dvc.exceptions import DvcException
from dvc.utils import relpath

logger = logging.getLogger(__name__)


class StageNotFound(KeyError, DvcException):
    def __init__(self, file, name):
        super().__init__(
            "Stage with '{}' name not found inside '{}' file".format(
                name, relpath(file)
            )
        )


def resolve_paths(path, wdir=None):
    path = os.path.abspath(path)
    wdir = wdir or os.curdir
    wdir = os.path.abspath(os.path.join(os.path.dirname(path), wdir))
    return path, wdir


class StageLoader(collections.abc.Mapping):
    def __init__(self, dvcfile, stages_data, lockfile_data=None):
        self.dvcfile = dvcfile
        self.stages_data = stages_data or {}
        self.lockfile_data = lockfile_data or {}

    @staticmethod
    def _fill_lock_checksums(stage, lock_data):
        from .stage import Stage

        outs = stage.outs if not stage.cmd_changed else []
        items = chain(
            ((Stage.PARAM_DEPS, dep) for dep in stage.deps),
            ((Stage.PARAM_OUTS, out) for out in outs),
        )
        for key, item in items:
            item.checksum = lock_data.get(key, {}).get(item.def_path)

    @classmethod
    def load_stage(cls, dvcfile, name, stage_data, lock_data):
        from .stage import PipelineStage, Stage, loads_from

        path, wdir = resolve_paths(
            dvcfile.path, stage_data.get(Stage.PARAM_WDIR)
        )
        stage = loads_from(PipelineStage, dvcfile.repo, path, wdir, stage_data)
        stage.name = name
        stage._fill_stage_dependencies(**stage_data)
        stage._fill_stage_outputs(**stage_data)
        if lock_data:
            stage.cmd_changed = lock_data.get(
                Stage.PARAM_CMD
            ) != stage_data.get(Stage.PARAM_CMD)
            cls._fill_lock_checksums(stage, lock_data)

        return stage

    def __getitem__(self, name):
        if name not in self:
            raise StageNotFound(self.dvcfile.path, name)

        if not self.lockfile_data.get(name):
            logger.warning(
                "No lock entry found for '%s:%s'", self.dvcfile.relpath, name
            )
        return self.load_stage(
            self.dvcfile,
            name,
            self.stages_data[name],
            self.lockfile_data.get(name, {}),
        )

    def __iter__(self):
        return iter(self.stages_data)

    def __len__(self):
        return len(self.stages_data)

    def __contains__(self, name):
        return name in self.stages_data


class SingleStageLoader(collections.abc.Mapping):
    def __init__(self, dvcfile, stage_data, stage_text=None):
        self.dvcfile = dvcfile
        self.stage_data = stage_data or {}
        self.stage_text = stage_text

    def __getitem__(self, item):
        if item:
            logger.warning(
                "Ignoring name '%s' for single stage in '%s'.",
                item,
                self.dvcfile,
            )
        # during `load`, we remove attributes from stage data, so as to
        # not duplicate, therefore, for MappingView, we need to deepcopy.
        return self.load_stage(
            self.dvcfile, deepcopy(self.stage_data), self.stage_text
        )

    @classmethod
    def load_stage(cls, dvcfile, d, stage_text):
        from dvc.stage import Stage, loads_from

        path, wdir = resolve_paths(dvcfile.path, d.get(Stage.PARAM_WDIR))
        stage = loads_from(Stage, dvcfile.repo, path, wdir, d)
        stage._stage_text, stage.tag = stage_text, dvcfile.tag
        stage.deps = dependency.loadd_from(
            stage, d.get(Stage.PARAM_DEPS) or []
        )
        stage.outs = output.loadd_from(stage, d.get(Stage.PARAM_OUTS) or [])
        return stage

    def __iter__(self):
        return iter([None])

    def __contains__(self, item):
        return False

    def __len__(self):
        return 1