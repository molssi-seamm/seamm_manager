Phase 0 notes -- manual migration on a clone (2026-09-25)
==========================================================

Setup
-----

``conda create -n seamm-pip-test --clone seamm`` (the production Mac
environment, Python 3.12.13, 366 packages of which 88 were pypi). Then::

    conda remove -n seamm-pip-test --force \
        molsystem seamm-dashboard seamm-datastore seamm-ff-util seamm-installer \
        seamm-util seamm-widgets reference-handler openbabel rdkit psutil pillow
    pip install molsystem seamm seamm-datastore seamm-ff-util seamm-installer \
        seamm-util seamm-widgets reference-handler openbabel rdkit psutil pillow

``reference-handler`` was added to the list: it is conda-forge in the
production environment but missing from the conda list in
``seamm_packaging``'s metadata. ``seamm`` itself was already a pip-installed
development build in production, so pip reported it as satisfied.

Results
-------

All checks pass on the migrated environment (script:
``phase0_checks.py``, kept in the session scratchpad; recreate from this
list if needed). The same script was run on the untouched ``seamm``
environment first and also passed, so the comparison is like for like.

================================================ ======================================
Check                                            Result on migrated env
================================================ ======================================
import openbabel / rdkit / psutil / PIL / spglib  OK, all from pip wheels
openbabel 3D build from SMILES                    OK, openbabel 3.2.1 wheel
rdkit embed                                       OK, rdkit 2026.3.6 wheel
molsystem SMILES -> OBMol -> RDKMol -> SDF        OK, molsystem 2026.9.20
**PIL.ImageTk PhotoImage under conda Tk 8.6**     **OK, Pillow 12.3.0 wheel**
seamm_datastore connect + initialize + login      OK
TkFlowchart created headlessly                    OK
``pip check``                                     no broken requirements
``conda env export`` on the mixed env             OK (269 conda, ~100 pip entries)
``conda list --explicit``                         OK
================================================ ======================================

The ImageTk result settles the main risk in the plan: the pip Pillow wheel
binds to the conda-forge Tk without any special handling. Pillow does not
need to stay a conda dependency.

Findings that change the plan
-----------------------------

1. **A targeted conda install is safe; ``conda update --all`` is not.**
   ``conda install --dry-run tk`` on the mixed environment touched only
   ``tk`` and ``openssl``: the solver treated the pip copies as satisfying
   the ``pillow``/``rdkit`` requirements of the remaining conda packages.
   But ``conda update --all --dry-run`` proposed 38 new and 228 updated
   packages, including:

   - a **conda ``pillow``** back on top of the pip one (pulled by
     ``matplotlib-base`` and ``reportlab``);
   - **``bibtexparser`` 1.4.3 -> 2.0.1**, straight through the ``<2``
     upper bound that four SEAMM packages declare -- conda does not read
     pip constraints;
   - ``sqlalchemy`` 1.4 -> 2.1, ``numpy`` 2.2 -> 2.5, and a conda ``pmw``
     over the pip ``pmw``.

   So the plan's Phase 5 "base update" must be ``conda install python pip
   tk libsqlite`` (targeted), never ``update --all``, and the user docs must
   say so. This is the same two-resolver failure the campaign exists to
   remove; it persists for as long as conda still owns Python packages.

2. **150 conda-managed Python packages remain** after moving the seven.
   They are the transitive dependencies conda pulled in originally
   (numpy, pandas, matplotlib, sqlalchemy, ...). While they exist, conda has
   something to "update" and finding 1 applies. The clean end state is
   *zero* conda Python packages: conda owns ``python``, ``pip``, ``tk``,
   ``libsqlite`` and their C libraries only. Two ways to get there:

   - **Fresh environment** (new installs, and the simplest fix for
     existing ones): ``conda create -n seamm python=3.12 pip tk`` then
     ``pip install`` the SEAMM package set. This is what the installer's
     ``seamm.yml`` should become.
   - **In-place**: force-remove every conda package whose build string is
     ``py312*`` or ``pyh*`` and re-``pip install`` the SEAMM set so pip
     re-resolves them. Not tested in Phase 0; the partial removal was.

   Recommendation: make the in-place migration in Phase 1 remove *all*
   conda Python packages, not just the seven, and offer "recreate the
   environment" as the documented alternative.

3. **The ``defaults`` channel is leaking into the environment.**
   ``create_env`` in ``seamm_installer/util.py`` writes ``channels:
   conda-forge, defaults``. Two packages in production come from
   ``pkgs/main``: ``apsw`` 3.51.1.0 and ``sqlite`` 3.53.2. The
   ``defaults`` ``sqlite`` and the conda-forge ``libsqlite`` 3.53.4 **both
   own ``lib/libsqlite3.dylib``**; in production the symlink points at
   3.53.4, in the clone it came out pointing at 3.53.2 (the clone re-linked
   in a different order). Python's ``sqlite3`` module therefore reports a
   different SQLite version in the two environments. Not caused by pip,
   but exactly the kind of silent inconsistency the ``!=3.49.1`` pin was
   meant to guard against. Drop ``defaults`` from ``create_env`` and from
   ``seamm.yml``; with everything else on pip there is no reason for it.

4. **Two packages are missing from the packaging metadata's conda list.**
   ``reference-handler`` is installed from conda-forge in production but
   listed nowhere in ``seamm_packaging``'s metadata (it is in
   ``seamm_installer/metadata.py``'s ``core_packages``). It must be in the
   Phase 1 force-removal set or a conda solve will keep it. The production
   ``seamm`` being a pip dev build also means the "seven" is really "six
   plus whatever the user has" -- the migration code should derive the set
   from ``conda list`` (channel != pypi, name in the package list) rather
   than from a hard-coded list.

5. **Version drift between channels is real.** The conda-forge
   ``molsystem`` in production was 2026.6.29; PyPI had 2026.9.20.
   ``seamm-ff-util`` 2025.8.1 vs 2026.9.20.1. ``seamm-util`` and
   ``seamm-widgets`` 2026.7.26/6.28 vs 2026.9.18. This is the "release
   lag" motivation, measured: two to three months behind on a machine that
   is updated regularly.

Environment left in place
-------------------------

``seamm-pip-test`` is still present for further poking (it is a full
2.4 GB clone). Remove with ``conda env remove -n seamm-pip-test`` when
done.
