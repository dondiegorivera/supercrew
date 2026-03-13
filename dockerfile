FROM sageil/crewai:1.10.0

USER root
RUN python -m pip install --no-cache-dir crewai litellm requests pypdf

WORKDIR /workspace

USER appuser
CMD ["python", "smoke_test.py"]
