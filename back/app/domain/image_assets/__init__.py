"""Character/scene image assets: closed preset vocabularies and the
server-side prompt builder that turns them into generation text.

`vocabulary` is the one source the request schema (and through `make
openapi` the frontend's unions), the prompt builder and the planner brief
all read, so a preset the studio offers is always one the pipeline knows
how to phrase.
"""
