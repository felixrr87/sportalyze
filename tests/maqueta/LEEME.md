# Comprobador de la maqueta

Carga `frontend/index.html` de verdad en un DOM, le pasa una edición
calculada por el motor y comprueba **que los números de la pantalla son
los números del modelo**. Una captura de pantalla dice si se ve bonito;
esto dice si una barra señala el puesto correcto.

## Ponerlo en marcha

```bash
cd tests/maqueta
npm install                 # trae jsdom, sólo la primera vez
python3 generar_edicion.py  # calcula edicion.json con el motor
npm run comprobar
```

O de una vez, desde la raíz:

```bash
python3 -m pytest tests/test_maqueta.py -v
```

Esa prueba se **salta** si no hay node o no está instalado jsdom, en
vez de fallar: el proyecto tiene que poder probarse sin node.

## Qué comprueba

- Las 20 filas, en el orden de la clasificación, con su nombre
- Que los puntos pintados son los que dio el motor
- Que cada barra del rango del 80 % cae donde le toca, a escala de 20
  puestos, y que la mediana queda dentro de su propia barra
- Que las tres partes de cada 1X2 suman el 100 % del ancho
- Que la procedencia (jornada, fecha, fuente, semilla) está en pantalla
- Que una probabilidad por debajo del 0,5 % se escribe `<1 %` y un cero
  exacto se escribe con una raya, no con `0 %`
- Que cuando no hay resultado se ve el cartel con el motivo **y** se
  esconde la tabla, sin dejar media pantalla a medias
- Que la página aguanta sin `localStorage`

## Lo que encontró

La primera vez que se ejecutó, la página entera se quedaba en blanco:
`index.html` leía `localStorage.getItem('sp_api')` en la primera línea
del script, y acceder a `localStorage` **lanza** una excepción en
ventana privada, con las cookies de sitio bloqueadas o en un iframe de
origen opaco. Al estar en el nivel de arriba se llevaba por delante el
resto del script. Está arreglado, y la prueba sigue ahí para que no
vuelva.
