#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

redis_container=voyageai-redis
api_url=http://127.0.0.1:8000
pids=()
services=()
stop_status=0
startup_pid=

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

check_docker() {
    command -v docker >/dev/null || fail 'Install Docker first.'
    command -v timeout >/dev/null || fail 'Missing command: timeout'
    timeout --foreground -k 2s 10s docker info >/dev/null || fail 'Start Docker and check access to the Docker daemon.'
    timeout --foreground -k 2s 10s docker compose version >/dev/null || fail 'Install the Docker Compose plugin.'
}

doctor() {
    local tool port listeners
    for tool in npm curl ss; do
        command -v "$tool" >/dev/null || fail "Missing command: $tool"
    done
    [[ -r backend/.env ]] || fail 'Set up backend/.env using backend/.env.example.'
    [[ -r frontend/.env ]] || fail 'Set up frontend/.env using frontend/.env.example.'
    [[ -x backend/.venv/bin/python ]] || fail 'Create backend/.venv and install backend/requirements.txt.'
    backend/.venv/bin/python -c 'import uvicorn, redis, sqlalchemy' || fail 'Install backend/requirements.txt in backend/.venv.'
    [[ -x frontend/node_modules/.bin/vite ]] || fail 'Run npm ci in frontend/.'
    check_docker
    for port in 8000 5173; do
        listeners=$(ss -H -ltn "sport = :$port") || fail "Could not check port $port."
        [[ -z $listeners ]] || fail "Port $port is in use. Stop the existing server and retry."
    done
    printf 'Local development prerequisites passed.\n'
}

wait_until_ready() {
    local service=$1
    shift
    local deadline=$((SECONDS + 45))
    local probe_output
    printf 'Waiting for %s to be ready...\n' "$service"
    until probe_output=$("$@" 2>&1); do
        if (( stop_status )); then
            return "$stop_status"
        fi
        if (( SECONDS >= deadline )); then
            if [[ -n $probe_output ]]; then
                printf '%s\n' "$probe_output" >&2
            fi
            fail "$service did not become ready. Check the startup logs and local .env settings."
        fi
        check_services
        sleep 1
    done
    printf '%s is ready.\n' "$service"
}

postgres_ready() {
    timeout --foreground -k 1s 3s docker exec cruiser_db pg_isready -h 127.0.0.1
}

redis_ready() {
    local response
    response=$(timeout --foreground -k 1s 3s docker exec "$redis_container" redis-cli ping) || return
    printf '%s\n' "$response"
    [[ $response == PONG ]]
}

api_ready() {
    curl --noproxy '*' --max-time 2 -fsS -o /dev/null "$api_url/openapi.json"
}

run_startup_command() {
    local service=$1 status=0
    shift
    # Waiting on a background job lets Bash handle Ctrl+C even if Docker is stuck.
    timeout -k 2s 90s "$@" </dev/null &
    startup_pid=$!
    if (( stop_status == 0 )); then
        wait "$startup_pid" || status=$?
    fi
    if (( stop_status )); then
        return "$stop_status"
    fi
    startup_pid=
    case "$status" in
        0) ;;
        124|137) fail "Docker timed out while starting $service." ;;
        *) fail "Docker failed to start $service (status $status). See the output above." ;;
    esac
}

start_infra() {
    local redis_id
    printf 'Starting PostgreSQL...\n'
    run_startup_command PostgreSQL docker compose --progress plain up -d db
    printf 'Starting Redis...\n'
    redis_id=$(timeout --foreground -k 2s 10s docker ps -aq --filter "name=^/${redis_container}$") \
        || fail 'Could not check for the Redis container. Check the Docker daemon.'
    if [[ -n $redis_id ]]; then
        run_startup_command Redis docker start "$redis_container"
    else
        run_startup_command Redis docker run -d --name "$redis_container" -p 127.0.0.1:6379:6379 redis:7-alpine
    fi

    wait_until_ready PostgreSQL postgres_ready
    wait_until_ready Redis redis_ready
}

stop_infra() {
    check_docker
    local status=0
    docker compose stop db || status=1
    if docker container inspect "$redis_container" >/dev/null 2>&1; then
        docker stop "$redis_container" || status=1
    fi
    return "$status"
}

start_service() {
    local service=$1 directory=$2
    shift 2
    (
        # Keep the service, its reload children and its log pipe in one process group.
        set +m
        cd "$directory"
        "$@" 2>&1 | sed -u "s/^/[$service] /"
    ) &
    pids+=("$!")
    services+=("$service")
}

check_services() {
    local i pid status
    for i in "${!pids[@]}"; do
        pid=${pids[i]}
        if ! kill -0 "$pid" 2>/dev/null; then
            status=0
            wait "$pid" || status=$?
            fail "${services[i]} exited unexpectedly (status $status). See its logs above."
        fi
    done
}

stop_services() {
    trap '' INT TERM
    local pid deadline=$((SECONDS + 10))
    if [[ -n $startup_pid ]]; then
        pids+=("$startup_pid")
    fi
    for pid in "${pids[@]}"; do
        kill -TERM -- "-$pid" 2>/dev/null || true
    done
    for pid in "${pids[@]}"; do
        while kill -0 -- "-$pid" 2>/dev/null && (( SECONDS < deadline )); do
            sleep 0.2
        done
        kill -KILL -- "-$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}

case "${1:-}" in
    start) ;;
    doctor) doctor; exit ;;
    stop) stop_infra; exit ;;
    *) fail 'Use make dev, make doctor or make stop.' ;;
esac

doctor
set -m
trap stop_services EXIT
trap 'stop_status=130' INT
trap 'stop_status=143' TERM

start_infra

printf 'Starting FastAPI...\n'
start_service api backend .venv/bin/python -u -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
wait_until_ready 'FastAPI' api_ready
start_service worker backend .venv/bin/python -u worker.py
start_service frontend frontend npm run dev -- --port 5173 --strictPort
printf 'API docs: http://localhost:8000/docs\n'
printf 'Press Ctrl+C to stop the API, worker and frontend.\n'

while (( stop_status == 0 )); do
    check_services
    sleep 1
done
exit "$stop_status"
