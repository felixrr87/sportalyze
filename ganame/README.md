# Sportalyze

Análisis de datos aplicado al fútbol. Cada pieza trae su código, sus datos y
sus comprobaciones, para que cualquiera pueda abrirla y tumbarla.

**Félix Ramírez** · [linkedin.com/in/felix-ramirez-tech](https://www.linkedin.com/in/felix-ramirez-tech)

---

## Gáname

Un modelo de probabilidad de gol, abierto y jugable.

→ **[felixrr87.github.io/sportalyze/ganame](https://felixrr87.github.io/sportalyze/ganame/)**

Te enseña diez parejas de tiros reales. En cada una, uno acabó en gol y el otro
no. Eliges cuál. Al final compites contra el modelo, y después puedes tocar
cualquier punto del campo para ver qué probabilidad le da y cuántos tiros
reales hay detrás de esa respuesta.

La página funciona sola: no llama a ningún servidor, no guarda nada y no
necesita instalar nada.

### Las cifras

| | |
|---|---|
| Tiros en juego | 29.224 |
| Goles | 4.358 (14,9 %) |
| Partidos | 1.680 |
| AUC | **0,7387** |
| Peor decil de calibración | 1,1 puntos |

El AUC es la frecuencia con la que el modelo ordena bien una pareja gol/fallo,
medida sobre las 108.366.028 parejas posibles. 0,5 sería no saber nada.

La calibración importa más y casi nunca se publica: parto los 29.224 tiros en
diez grupos según lo que el modelo les daba y comparo con lo que pasó.

| Dice | Pasa |
|---|---|
| 3,0 % | 2,6 % |
| 5,2 % | 4,8 % |
| 10,9 % | 10,3 % |
| 16,0 % | 16,6 % |
| 19,8 % | 20,2 % |
| 38,6 % | 39,7 % |

### Lo que el modelo no sabe

Sólo conoce **desde dónde** se tiró. No sabe si fue con la cabeza, si venía de
un contraataque, ni si había un defensa delante. Por eso acierta el 73,9 % de
las parejas y no el 85 %. No distingue a Messi de un central. Y donde hay menos
de 40 tiros equivalentes detrás, no pinta nada: podría rellenarlo y quedaría
más bonito, pero sería inventado.

### Cómo se regenera

```bash
cd ganame/codigo
python3 exportar.py     # corre el modelo y saca datos.json
python3 montar.py       # mete los datos en la página
python3 video.py        # el vídeo para el feed
```

`exportar.py` tarda un par de minutos y va guardando por el camino, así que se
puede cortar y reanudar.

### Por qué las parejas son parejas

La primera versión enseñaba diez tiros sueltos y pedía una probabilidad para
cada uno. Era un juego roto: sólo el 14,9 % de los tiros acaban en gol, así que
se ganaba diciendo «no entra» diez veces sin mirar. La tirada con la semilla de
siempre salió con cero goles de diez y lo dejó claro.

No cambié la semilla hasta que saliera una muestra bonita. Cambié el juego, que
era lo que estaba mal. Está escrito en la cabecera de `exportar.py`.

### Las comprobaciones

Los scripts se paran antes que publicar un número que no cuadre:

- `exportar.py` comprueba que el modelo mejora a decir siempre la media, que
  ningún decil de calibración se desvía más de 6 puntos, que el AUC está en un
  rango creíble, que cada pareja tiene exactamente un gol y un fallo, y que el
  gol no cae casi siempre del mismo lado.
- `montar.py` reimplementa en Python la fórmula del ángulo que usa el
  JavaScript de la página y la compara con la del modelo en 733 puntos del
  campo. Si el navegador dijera algo distinto a lo que calcula el modelo, no
  sale página. Desvío medido: 0,000000 grados.
- `video.py` cuenta los fotogramas idénticos al anterior y revienta si el vídeo
  se ha quedado congelado. Saltó de verdad la primera vez: 383 de 759.

### Datos

[StatsBomb open data](https://github.com/statsbomb/open-data). Penaltis fuera.

---

*Si en tu club o en tu empresa hay una pregunta que los datos podrían contestar
y nadie está mirándola, escríbeme.*
