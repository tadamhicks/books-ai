IMAGE_REGISTRY ?= docker.io/tadamhicks
IMAGE_NAME ?= books-ai-api
IMAGE_TAG ?= 0.3.0
IMAGE := $(IMAGE_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

.PHONY: build push run hooks

build:
	container build --tag $(IMAGE) .

push:
	container push $(IMAGE)

run:
	container run --publish 8000:8000 $(IMAGE)

hooks:
	./scripts/install-git-hooks.sh
