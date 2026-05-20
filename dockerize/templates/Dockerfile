FROM scratch
COPY . /

{% if labels -%}
LABEL {% for key, value in labels.items() %}{{key}}="{{value}}"{% if not loop.last %} \
      {% endif %}{% endfor %}
{% endif -%}
{% if docker.entrypoint -%}
ENTRYPOINT {{docker.entrypoint}}
{% endif -%}
{% if docker.cmd -%}
CMD {{docker.cmd}}
{% endif -%}
