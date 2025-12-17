CONTAINER ?= container
IMAGE_REGISTRY ?= docker.io/tadamhicks
IMAGE_NAME ?= books-ai-api
IMAGE_TAG ?= 0.1.7
IMAGE := $(IMAGE_REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

.PHONY: build push run hooks

build:
	$(CONTAINER) build --platform linux/amd64 -t $(IMAGE) .

push:
	$(CONTAINER) image push $(IMAGE)

run:
	$(CONTAINER) run --rm -p 8000:8000 $(IMAGE)

hooks:
	./scripts/install-git-hooks.sh

