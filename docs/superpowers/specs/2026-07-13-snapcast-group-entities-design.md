# Entidades de grupos Snapcast — Diseño

## Objetivo

Restaurar los grupos reales de Snapcast como entidades `media_player` controlables y mantener estables sus entidades de Home Assistant cuando Snapcast sustituya el ID físico del grupo.

## Contexto y causa

La integración actual solo descubre `server.clients`, por lo que no crea entidades para `server.groups`. Home Assistant retiró las entidades de grupo de su integración oficial al adoptar las acciones estándar de agrupación. Snapcast Plus conserva las entidades de clientes y añade de nuevo las de grupos.

Los ID de grupo de Snapcast son efímeros: al unir o separar clientes el servidor puede eliminar un grupo y crear otro con un ID distinto. Usar ese ID como identidad permanente rompería dashboards y automatizaciones.

## Arquitectura

### Identidad lógica persistente

Un gestor de identidades de grupo, por entrada de configuración, se persistirá mediante `homeassistant.helpers.storage.Store`. Cada registro mantiene:

- `logical_id`: identidad estable, inicialmente el ID físico del grupo.
- `physical_id`: ID actual que usa Snapcast.
- `member_ids`: IDs de cliente de la última composición observada.

La entidad usará `snapcast_group_{host}:{port}_{logical_id}` como `unique_id` y resolverá el grupo actual mediante `physical_id` en cada acceso. Esto conserva la compatibilidad con los `unique_id` históricos cuando el ID no ha cambiado y evita referencias a objetos `Snapgroup` anteriores a una reconexión.

### Reconciliación automática

En cada actualización del coordinador, el gestor compara los grupos actuales con sus registros:

1. Coincide primero por ID físico.
2. Para grupos nuevos, vincula por conjunto de miembros idéntico.
3. Si no hay coincidencia exacta, vincula por el mayor número de miembros compartidos solo cuando el mejor candidato es único.
4. Si hay empate o no hay miembros compartidos, crea una identidad lógica nueva y conserva las anteriores como no resueltas.

El algoritmo asigna cada grupo físico y cada identidad lógica como máximo una vez en una pasada. Una identidad no resuelta permanece registrada pero su entidad está `unavailable`; no se borra, pues puede reaparecer o ser reconciliada manualmente.

### Recuperación manual

El servicio `snapcast.reconcile_group` acepta `old_entity_id` y `new_entity_id`. Ambos deben ser entidades de grupo de la misma entrada de Snapcast. El servicio reasigna el ID físico de la entidad antigua al grupo detectado, persiste el cambio, elimina la entidad duplicada del registro y recarga solo esa entrada. Al reiniciar las plataformas, la entidad antigua vuelve a representar el grupo actual sin cambiar su `entity_id`.

No se hará una reasignación automática en un caso ambiguo. Esto impide controlar por accidente un grupo distinto.

## Entidad de grupo

`SnapcastGroupDevice` será un `MediaPlayerEntity` con:

- nombre `<nombre-del-grupo> Snapcast Group`;
- estado derivado de `stream_status` y mute del grupo;
- controles de volumen, mute y selección de fuente;
- `snapshot` y `restore` mediante los servicios existentes;
- acceso a datos siempre fresco desde el coordinador;
- disponibilidad basada en la conexión del coordinador y en la existencia del grupo físico.

La entidad no expondrá `GROUPING`, no permitirá `media_player.join`/`unjoin` ni `snapcast.set_latency`; estas son operaciones de cliente. La llamada a latencia contra un grupo devuelve un error explicativo.

## Compatibilidad y errores

- Las entidades de cliente, sensores y servicios existentes mantienen su comportamiento.
- Las entidades históricas cuyo ID físico todavía existe se adoptan automáticamente por su `unique_id` previo.
- No es posible asociar de forma fiable una entidad histórica ya ausente sin historial de miembros; el servicio manual proporciona esa elección explícita.
- Grupos ausentes, desconexiones y grupos no encontrados no lanzan errores desde propiedades de estado: exponen `unavailable` o valores vacíos.

## Pruebas

La suite deberá demostrar:

1. Descubrimiento inicial de grupos y controles de grupo.
2. Reasignación conservando el `entity_id` cuando cambia el ID físico con mismos miembros.
3. Reasignación por solapamiento de miembros solo cuando es inequívoca.
4. No reasignación automática ante empate.
5. Persistencia de la asignación a través de una recarga de entrada.
6. Recuperación manual de una entidad antigua y retiro de la entidad duplicada.
7. Resolución fresca del grupo después de una reconexión.
8. Ausencia de regresiones en clientes y sensores existentes.
