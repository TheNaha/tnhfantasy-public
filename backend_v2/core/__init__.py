# Core package marker — intentionally empty.
#
# This file used to re-export ~40 domain names (entities, events, exceptions,
# workflow parsing). Nothing in the tree ever imported through it: there is not
# a single `from core import <name>` in the repo, only `from core.entities
# import ...`, `from core.exceptions import ...`, `import core.events` and the
# like. The re-export list was ~82 lines of a second import surface to keep in
# sync with the submodules, and `__all__` gave no hint which one was canonical.
#
# `core` is the pure-domain layer: entities/entities_v2 (ORM), dtos, events,
# exceptions, workflow_parser. Import the submodule you need.
#
# If you add a re-export here, also add the `from core import X` consumer that
# needs it. Prefer importing the submodule directly.
