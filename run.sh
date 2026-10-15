#!/bin/bash
# study-tips 看板服务管理: ./run.sh start|stop|restart|status
# 开机自启：crontab 加一行 @reboot /home/steven/study-tips-kb/run.sh start
DIR="$(cd "$(dirname "$0")" && pwd)"
PORT=8001
cd "$DIR" || exit 1
mkdir -p logs

alive() {
  curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:$PORT/health"
}

case "${1:-start}" in
  start)
    if alive; then
      echo "已在运行 (port $PORT)"
    else
      nohup python3 "$DIR/server.py" >> "$DIR/logs/server.log" 2>&1 &
      sleep 1
      if alive; then
        echo "已启动 pid=$! (port $PORT)"
      else
        echo "启动失败，查看 logs/server.log"
        exit 1
      fi
    fi
    ;;
  stop)
    if pkill -f "python3 $DIR/server.py"; then
      echo "已停止"
    else
      echo "未在运行"
    fi
    ;;
  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;
  status)
    if alive; then
      echo "运行中 (port $PORT)"
    else
      echo "未运行"
    fi
    tail -5 "$DIR/logs/server.log" 2>/dev/null
    ;;
  *)
    echo "用法: $0 start|stop|restart|status"
    exit 1
    ;;
esac
