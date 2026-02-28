# Prácticas Necesarias para un Repositorio en GitHub

Guía comprehensiva de mejores prácticas para configurar y mantener repositorios de GitHub profesionales.

---

## 1. Documentación Esencial

| Archivo | Propósito |
|---------|-----------|
| `README.md` | Descripción del proyecto, instalación, uso y ejemplos |
| `LICENSE` | Licencia del proyecto (MIT, GPL, Apache, etc.) |
| `CONTRIBUTING.md` | Guía para contribuidores |
| `CODE_OF_CONDUCT.md` | Código de conducta de la comunidad |
| `SECURITY.md` | Políticas de seguridad y reporte de vulnerabilidades |
| `CHANGELOG.md` | Historial de cambios por versión |
| `SUPPORT.md` | Cómo obtener ayuda |

---

## 2. Configuración del Repositorio

- **Nombre descriptivo**: que refleje el propósito del proyecto
- **Topics/etiquetas**: para mejorar la descubribilidad
- **Descripción y URL**: en la sección "About"
- **`.gitignore`**: excluir archivos locales, dependencias, secretos y configuraciones personales

---

## 3. Seguridad

A mínimo, habilitar las siguientes características (gratuitas para repositorios públicos):

- **Dependabot alerts**: notificaciones de vulnerabilidades en dependencias
- **Secret scanning**: detección de API keys y tokens expuestos
- **Push protection**: bloqueo de pushes que contienen secretos
- **Code scanning (CodeQL)**: identificación de vulnerabilidades en el código
- **2FA obligatorio**: para todos los colaboradores
- **Principio de mínimo privilegio**: solo otorgar el nivel mínimo de acceso necesario

---

## 4. Protección de Ramas

Para la rama principal (`main` o `master`), configurar:

- [ ] Bloquear force pushes y eliminaciones
- [ ] Requerir pull requests antes de merge
- [ ] Requerir status checks (CI/CD) aprobados
- [ ] Requerir revisiones de código (1-2 aprobaciones mínimo)
- [ ] Usar `CODEOWNERS` para asignar revisores automáticamente

---

## 5. CI/CD y Automatización

### GitHub Actions

- Pipelines automatizados para build, test y deploy
- Tests automatizados en cada PR
- Linting y formateo de código
- Semantic versioning con releases automáticos

### Dependabot

- Actualizaciones automáticas de dependencias
- Configurar en `.github/dependabot.yml`

---

## 6. Gestión de Dependencias

- No incluir dependencias en el repositorio
- Dejar que el package manager las descargue en cada build
- Especificar versiones exactas o rangos en el archivo de manifiesto
- Usar lock files (`package-lock.json`, `poetry.lock`, etc.)

---

## 7. Commits y Branching

### Conventional Commits

Formato recomendado para mensajes de commit:

```
<tipo>[alcance opcional]: <descripción>

[cuerpo opcional]

[pie opcional]
```

**Tipos comunes:**
- `feat`: nueva funcionalidad
- `fix`: corrección de bug
- `docs`: documentación
- `style`: formateo
- `refactor`: refactorización
- `test`: tests
- `chore`: mantenimiento

### Automatización de Commits (Entornos sin TTY / Agentes)
Cuando se usen herramientas como `commitizen` asistidas por pipelines CI/CD o Agentes Autónomos Inteligentes:
- **Evitar prompts interactivos**: No invocar comandos que exijan selección con flechas (ej. `cz commit` a secas). Éstos bloquearán el flujo.
- **Usar llamadas atómicas**: Inyectar los mensajes como parámetros (`cz commit -m "fix(scope): msg"`) o confiar en `git commit` estructurado adecuadamente; Commitizen será capaz de leer el historial con `cz changelog` posteriormente sin problemas.

### Estrategias de Branching

- **GitHub Flow**: simple, ideal para deploy continuo
- **GitFlow**: más complejo, para releases programados
- **Trunk-based**: commits frecuentes a main

### Buenas Prácticas

- Commits atómicos con mensajes descriptivos
- Configurar email correctamente para evitar autores no reconocidos
- Archivar repositorios sin mantenimiento en lugar de eliminarlos

---

## 8. Estructura de Directorios

```
proyecto/
├── .github/
│   ├── workflows/              # GitHub Actions
│   │   ├── ci.yml
│   │   └── release.yml
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
├── docs/                       # Documentación extendida
├── src/                        # Código fuente
├── tests/                      # Tests
├── .gitignore
├── .editorconfig
├── README.md
├── LICENSE
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── CHANGELOG.md
└── ...
```

---

## 9. Templates Recomendados

### Issue Template (Bug Report)

```markdown
## Descripción del Bug
[Descripción clara y concisa]

## Pasos para Reproducir
1. Ir a '...'
2. Click en '...'
3. Ver error

## Comportamiento Esperado
[Qué debería pasar]

## Screenshots
[Si aplica]

## Entorno
- OS: [e.g., Windows 11]
- Versión: [e.g., 1.0.0]
```

### Pull Request Template

```markdown
## Descripción
[Descripción de los cambios]

## Tipo de Cambio
- [ ] Bug fix
- [ ] Nueva funcionalidad
- [ ] Breaking change
- [ ] Documentación

## Checklist
- [ ] Tests agregados/actualizados
- [ ] Documentación actualizada
- [ ] Código formateado
```

---

## 10. Checklist de Configuración Inicial

### Repositorio Nuevo

- [ ] Crear README.md con descripción clara
- [ ] Agregar LICENSE apropiada
- [ ] Configurar .gitignore
- [ ] Habilitar branch protection en main
- [ ] Configurar Dependabot
- [ ] Habilitar secret scanning
- [ ] Habilitar code scanning
- [ ] Agregar topics relevantes
- [ ] Configurar GitHub Actions básico

### Repositorio Existente

- [ ] Auditar permisos de acceso
- [ ] Revisar y actualizar dependencias
- [ ] Verificar configuración de seguridad
- [ ] Actualizar documentación
- [ ] Archivar branches obsoletas

---

## Referencias

- [GitHub Docs - Best Practices for Repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories)
- [GitHub Well-Architected - Rulesets Best Practices](https://wellarchitected.github.com/library/governance/recommendations/managing-repositories-at-scale/rulesets-best-practices/)
- [Conventional Commits](https://www.conventionalcommits.org/)

---

*Documento generado el 2026-01-04*