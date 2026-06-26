# Build from ~/Projects:
#   docker build -f raphael-workspaces/Dockerfile .
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY raphael-contracts /deps/raphael-contracts
RUN uv pip install --system /deps/raphael-contracts
COPY raphael-workspaces/pyproject.toml raphael-workspaces/README.md ./
COPY raphael-workspaces/src ./src
RUN python3 -c "import re; from pathlib import Path; p=Path('pyproject.toml'); p.write_text(re.sub(r'\n\[tool\.uv\.sources\][^\[]*','\n',p.read_text(),flags=re.S))"
RUN uv pip install --system -e .
ENV RAPHAEL_SERVICE_PORT=8083
EXPOSE 8083
CMD ["uvicorn", "raphael_workspaces.app:app", "--host", "0.0.0.0", "--port", "8083"]
