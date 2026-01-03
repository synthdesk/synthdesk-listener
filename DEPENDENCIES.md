# Runtime Dependencies

## synthdesk-spine

**Version:** 0.1.0 (major.minor contract: 0.1.x)

**Location:** `../spine_sdk` (in parent monorepo)

**Purpose:** Canonical event envelope schema and spine substrate

**Installation:**
```bash
cd ../spine_sdk
pip3 install -e .
```

**Version Contract:**
- **Major version must match exactly** (hard requirement enforced at startup)
- **Minor version mismatch** triggers warning but allows execution
- Breaking changes in spine SDK require updating `REQUIRED_SPINE_MAJOR/MINOR` in `synthdesk_listener/main.py`

**Verification:**
```python
import synthdesk_spine
print(synthdesk_spine.__version__)  # Should be 0.1.0
```

## Python Version

**Required:** Python 3.10+

**Recommended:** Python 3.12 (matches VPS production environment)

**Note on Determinism:**
- Event spine replay determinism requires **identical Python version** between local and production
- Event IDs use SHA-256 hashing which can vary subtly across Python versions
- Always verify `python_version` in `listener.start` events matches replay environment

## Known RuntimeWarning

**Warning Message:**
```
RuntimeWarning: 'synthdesk_listener.main' found in sys.modules after import
of package 'synthdesk_listener', but prior to execution of 'synthdesk_listener.main';
this may result in unpredictable behaviour
```

**Status:** Known, cosmetic, no functional impact

**Cause:** Module import ordering in package structure when executed as `-m synthdesk_listener.main`

**Action:** Deferred for investigation post-soak test (see issue tracker)

**Mitigation:** None required - warning is benign

## Updating Dependencies

### When spine SDK version changes:

1. Update spine SDK locally (`cd ../spine_sdk && git pull`)
2. Reinstall: `pip3 install -e ../spine_sdk`
3. Update version contract in `synthdesk_listener/main.py`:
   ```python
   REQUIRED_SPINE_MAJOR = X
   REQUIRED_SPINE_MINOR = Y
   ```
4. Test locally to verify compatibility
5. Deploy to VPS (see DEPLOY.md)

### VPS Deployment Checklist:

- [ ] Verify spine SDK version on VPS matches local
- [ ] Check `python_version` in latest `listener.start` event
- [ ] Monitor first 100 events for schema consistency
- [ ] Verify event spine continuity (event count increasing)
