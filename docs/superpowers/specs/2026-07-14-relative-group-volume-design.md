# Volumen relativo para grupos Snapcast — Diseño

## Objetivo

Recuperar el control visible de mute en la interfaz de Home Assistant para los
grupos dinámicos de Snapcast, sin convertir sus clientes a un volumen uniforme.

## Decisión

Los `media_player` de grupo expondrán `VOLUME_SET` además de `VOLUME_MUTE` y
selección de fuente. El slider muestra `Snapgroup.volume`, que es el promedio
actual de los clientes, normalizado entre 0 y 1.

Al mover el slider, la integración llamará únicamente a
`Snapgroup.set_volume(round(volume_level * 100))`. La biblioteca `snapcast`
distribuye el cambio proporcionalmente entre los clientes: para bajar escala
cada volumen según su nivel actual; para subir usa el margen restante de cada
cliente hasta 100. No se escribirá el mismo valor en todos los clientes.

Home Assistant muestra su botón de mute dentro del bloque de volumen y requiere
`VOLUME_SET` o `VOLUME_STEP`; por eso este cambio devuelve a la UI tanto el
slider como mute.

## Límites

- Solo cambian las entidades de grupo dinámico.
- Las zonas persistentes siguen con mute y source, sin volumen: una zona puede
  abarcar varios grupos con promedios diferentes, por lo que no tiene un único
  valor de slider que sea claro.
- Los grupos siguen sin snapshot, restore y latencia.
- La integración no recalcula ni distribuye volúmenes por su cuenta.

## Pruebas

1. Un grupo publica `volume_level` como el promedio de Snapcast dividido entre
   100 y anuncia `VOLUME_SET`.
2. `media_player.volume_set` en un grupo delega el porcentaje entero a
   `Snapgroup.set_volume`; no realiza llamadas directas a clientes.
3. Las zonas no publican `volume_level` ni soportan volumen.
4. El README explica que el volumen de grupo es relativo y que también hace
   visible mute en el diálogo nativo de Home Assistant.
