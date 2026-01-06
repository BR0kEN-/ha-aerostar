.DEFAULT_GOAL := venv
.PHONY: venv

venv:
	test -d venv || python3 -m venv venv

pu:
	pip3 install --upgrade pip

i: pu
	pip3 install -e '.[dev]'
