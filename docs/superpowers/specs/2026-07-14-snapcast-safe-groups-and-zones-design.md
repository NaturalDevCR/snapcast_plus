# Grupos seguros y zonas persistentes de Snapcast — Diseño

## Objetivo

Exponer los grupos reales de Snapcast sin atribuirles una identidad que el
servidor no garantiza, y ofrecer zonas estables, definidas por el usuario,
para automatizaciones como «Casa» o «Planta baja».

## Decisiones de producto

### Grupos dinámicos

Cada grupo vivo continúa siendo un `media_player`, con `mute` y selección de
fuente. No tendrá control de volumen, `snapshot`, `restore` ni latencia. El
volumen de un grupo de Snapcast modifica los volúmenes de sus clientes y no
representa un control de zona independiente.

La identidad lógica se guarda por entrada de configuración. Un grupo conserva
su entidad solamente cuando:

1. el ID físico de Snapcast permanece, o
2. el ID cambia y hay exactamente una entidad desaparecida con el mismo
   conjunto completo de IDs de cliente.

No se usa solapamiento parcial. En una unión o división, una coincidencia
parcial puede asignar una automatización a la mitad equivocada de una casa.
Las entidades no resueltas se conservan como `unavailable`; los grupos nuevos
reciben una nueva identidad.

### Reconciliación manual

`snapcast.reconcile_group` recibe `old_entity_id` y `new_entity_id`. Ambas
entidades deben ser grupos de la misma entrada de Snapcast. La operación mueve
el ID físico activo de la entidad nueva a la antigua, persiste el cambio,
elimina el registro de la duplicada y recarga únicamente esa entrada. La
entidad antigua conserva su `entity_id`.

### Zonas persistentes

Una zona está formada por uno o más `media_player` de clientes Snapcast de la
misma entrada. Se almacena un UUID y los IDs físicos de cliente; su `unique_id`
no depende de los grupos actuales. Las zonas se administran con servicios:

- `snapcast.create_zone(name, clients)`
- `snapcast.update_zone(zone_entity_id, name?, clients?)`
- `snapcast.remove_zone(zone_entity_id)`

Sus entidades son `media_player` con mute y fuente. Para cada acción, resuelven
en ese instante los grupos distintos que contienen a sus clientes:

- mute se aplica a todos esos grupos;
- una fuente se aplica a todos, únicamente si la fuente existe en todos;
- `source` solo se publica cuando todos usan la misma fuente;
- `source_list` es la intersección de fuentes disponibles;
- una zona sin clientes o grupos vivos queda `unavailable`.

Así, «Casa» sigue existiendo cuando Snapcast crea, destruye, une o divide
grupos. Si sus clientes quedan en varios grupos, una sola acción de zona llega
a cada uno de esos grupos.

## Compatibilidad y persistencia

- Se conserva el dominio `snapcast` y los `unique_id` históricos de clientes y
  grupos.
- Los grupos ya persistidos se leen con el mismo almacén de datos. Solo cambia
  la política de reconciliación para futuras actualizaciones.
- Las zonas se guardan en un almacén independiente por entrada.
- Ninguna entidad conserva referencias a objetos `Snapgroup` o `Snapclient`
  entre actualizaciones o reconexiones.

## Pruebas requeridas

1. Un cambio de ID con miembros idénticos conserva la entidad de grupo.
2. Una coincidencia parcial no reasigna la entidad antigua.
3. El servicio manual reasigna una entidad antigua y retira el duplicado.
4. Una zona sobre clientes que cambian de grupo conserva su entidad y controla
   los grupos actuales distintos.
5. Una zona rechaza clientes ajenos a la entrada y fuentes no comunes.
6. Los grupos y zonas no exponen volumen ni snapshot/restore.
7. El README documenta cada entidad, servicio y la estrategia de recuperación.
