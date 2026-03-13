FROM sageil/crewai:1.10.0

USER root
RUN python -m pip install --no-cache-dir crewai litellm requests pypdf
RUN chmod -R a+rX /home/appuser/.local/lib/

WORKDIR /workspace

CMD ["python", "-u", "supercrew.py"]
