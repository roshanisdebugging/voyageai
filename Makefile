.DEFAULT_GOAL := help
.PHONY: help dev doctor stop

help:
	@printf '%s\n' 'make dev     Start the local development stack' \
		'make doctor  Check local development prerequisites' \
		'make stop    Stop the local PostgreSQL and Redis containers'

dev:
	@bash scripts/dev.sh start

doctor:
	@bash scripts/dev.sh doctor

stop:
	@bash scripts/dev.sh stop
