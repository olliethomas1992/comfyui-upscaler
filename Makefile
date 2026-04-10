.PHONY: test-unit test-build mock-volume test-local test-health test-integration clean

test-unit:
	pytest tests/test_handler_unit.py -v

test-build:
	./tests/test_build.sh

mock-volume:
	./tests/create_mock_volume.sh

test-local: mock-volume
	docker compose -f docker-compose.test.yml up

test-health:
	./tests/test_health.sh

test-integration:
	./tests/test_integration.sh

clean:
	docker compose -f docker-compose.test.yml down 2>/dev/null || true
	rm -rf test-volume/
