# A/B real: carriles por proveedor (#3763)

Workers Dramatiq reales contra un Redis aislado local (redis-server 6.0.16 en
127.0.0.1, un servidor nuevo por corrida, `--save '' --appendonly no`,
maxmemory 64mb). Sin red externa, sin DB de prod, sin backups concurrentes.

## Comando exacto

    python run_ab.py --pares 5 --largo 20 --corto 0.5 --semilla 31 --out /tmp/ab-carriles.jsonl

(--desde N permite reanudar; cada par se anexa al JSONL.)

Preparacion del redis aislado (sin root):

    apt-get download redis-tools redis-server
    dpkg -x redis-tools_*.deb /tmp/redis-bin && dpkg -x redis-server_*.deb /tmp/redis-bin2
    ln -sf /tmp/redis-bin/usr/bin/redis-check-rdb /tmp/redis-bin/usr/bin/redis-server

## Carga (identica en A y B, semilla fija)

2 largos de 20 s primero (ocupan los 2 hilos, forma del incidente del 31-oct)
+ 20 cortos de 0,5 s; la semilla (31 + nº de par) solo baraja el orden interno
de los cortos. Los pares alternan el orden A/B para no sesgar por deriva.

- A (actual): 1 worker, 2 hilos, cola compartida.
- B (propuesta): 2 workers de 2 hilos, colas largo/corto.

Metrica: segundos desde el primer encolado hasta que termina el ultimo corto.

## Resultado medido (31-oct, esta VM)

| Par | A (compartida) | B (carriles) |
|-----|---------------|--------------|
| 1   | 25,277 s      | 5,098 s      |
| 2   | 25,111 s      | 5,141 s      |
| 3   | 25,529 s      | 5,469 s      |
| 4   | 25,354 s      | 5,479 s      |
| 5   | 25,527 s      | 5,279 s      |

Mediana A: **25,354 s** · Mediana B: **5,279 s** · **Mejora: 4,8x** en el
tiempo de espera del trafico corto durante corridas largas. El makespan total
no empeora (A 25,4 s vs B 20,6 s: B tambien termina antes el conjunto).

Recursos: 3 procesos como mucho por corrida (redis + 2 workers), actores que
solo duermen; sin CPU sostenida.
