# Infrastructure package marker — intentionally empty.
#
# This file used to re-export ~50 names from the submodules below, which made
# `from infrastructure import <name>` look like the supported entry point. It
# never was: every consumer in the tree imports the submodule it needs
# directly (`from infrastructure.database import ...`,
# `import infrastructure.logging`, `from infrastructure.cache import ...`),
# and there are no star imports. Python resolves those submodule imports
# whether or not this package re-exports anything, so the re-export list was
# ~126 lines that only had to be kept in sync.
#
# It also had a real cost: `from .database import engine` here meant that
# merely importing *any* submodule constructed the SQLAlchemy engine as a side
# effect. Dropping the barrel removes that hidden coupling — a module that
# wants the engine asks for it.
#
# If you add a re-export here, also add the `from infrastructure import X`
# consumer that needs it. Prefer importing the submodule directly.
