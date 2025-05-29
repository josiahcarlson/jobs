FILES=`ls docker-compose.*.yaml`
# A little nasty here, but we can do it!
# The grep finds the 'rom-test-<service version>' in the .yaml
# The sed removes extra spaces and colons
# Which we pass into our rebuild
GET_TARGET=grep jobs-test docker-compose.$${target}.yaml | sed 's/[ :]//g'
COMPOSE_PREFIX=docker-compose -f docker-compose.

SHELL=/bin/bash
# You can set these variables from the command line.
SPHINXOPTS    =
SPHINXBUILD   = sphinx-build
PAPER         =
BUILDDIR      = _build

# User-friendly check for sphinx-build
#ifeq ($(shell which $(SPHINXBUILD) >/dev/null 2>&1; echo $$?), 1)
#$(error The '$(SPHINXBUILD)' command was not found. Make sure you have Sphinx installed, then set the SPHINXBUILD environment variable to point to the full path of the '$(SPHINXBUILD)' executable. Alternatively you can add the directory with the executable to your PATH. If you don't have Sphinx installed, grab it from http://sphinx-doc.org/)
#endif

# Internal variables.
PAPEROPT_a4     = -D latex_paper_size=a4
PAPEROPT_letter = -D latex_paper_size=letter
ALLSPHINXOPTS   = -d $(BUILDDIR)/doctrees $(PAPEROPT_$(PAPER)) $(SPHINXOPTS) _docs
# the i18n builder cannot share the environment and doctrees with the others
I18NSPHINXOPTS  = $(PAPEROPT_$(PAPER)) $(SPHINXOPTS) .

clean:
	-rm -f *.pyc README.html MANIFEST
	-rm -rf build dist

install:
	python -m pip install .


compose-build-all:
	echo ${FILES}
	for target in ${FILES} ; do \
		docker-compose -f $${target} build -- `${GET_TARGET}` redis-data-storage; \
	done

compose-build-%:
	for target in $(patsubst compose-build-%,%,$@) ; do \
		${COMPOSE_PREFIX}$${target}.yaml build `${GET_TARGET}`; \
	done


compose-up-%:
	for target in $(patsubst compose-up-%,%,$@) ; do \
		${COMPOSE_PREFIX}$${target}.yaml up --remove-orphans `${GET_TARGET}`; \
	done

compose-down-%:
	for target in $(patsubst compose-down-%,%,$@) ; do \
		${COMPOSE_PREFIX}$${target}.yaml down `${GET_TARGET}`; \
	done

testall:
	# they use the same Redis, so can't run in parallel
	make -j1 test-3.11 test-3.10 test-3.9 test-3.8 test-3.7 test-3.6 test-3.5 test-3.4 test-2.7

test-%:
	# the test container runs the tests on up, then does an exit 0 when done
	for target in $(patsubst test-%,%,$@) ; do \
		make compose-build-$${target} && make compose-up-$${target}; \
	done


upload: docs
	git tag `cat VERSION`
	git push origin --tags
	python3.6 -m build
	python3.6 -m twine upload --verbose dist/jobspy-`cat VERSION`.tar.gz

docs:
	python -c "import jobs; open('VERSION', 'wb').write(jobs.VERSION);open('README.rst', 'wb').write(jobs.__doc__);"
	docker-compose -f docker-compose.docs.yaml build
	docker-compose -f docker-compose.docs.yaml run jobs-test-docs $(SPHINXBUILD) -b html $(ALLSPHINXOPTS) /app/_build/html
	cd docs/ && zip -r9 ../jobs_docs.zip .
	@echo
	@echo "Build finished."
