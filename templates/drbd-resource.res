resource export {
        device /dev/drbd0;
        disk {{ block_device }}1;
        meta-disk internal;
        {% for unit, address in units.iteritems() -%}
        on {{ unit }} {
                address {{ address }}:7788;
        }
        {% endfor %}
        syncer {
                rate 10M;
        }
}

