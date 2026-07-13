import os
import re
import glob

routes_dir = "backend_v2/api/routes"
files = glob.glob(f"{routes_dir}/**/*.py", recursive=True)

FACTORIES = {
    "get_collection_repo": ("CollectionRepository", "infrastructure.repositories.collection_repo"),
    "get_provider_service": ("ProviderService", "services.provider_service"),
    "get_job_submission_service": ("JobSubmissionService", "services.job_submission_service"),
    "get_job_service": ("JobService", "services.job_service"),
    "get_model_repo_v2": ("ModelRepoV2", "infrastructure.repositories.model_repo_v2"),
    "get_model_civitai_sync_service": ("ModelCivitaiSyncService", "services.model_civitai_sync_service"),
    "get_model_service_v2": ("ModelServiceV2", "services.model_service"),
    "get_provider_lifecycle_service": ("ProviderLifecycleService", "services.provider_lifecycle_service"),
    "get_provider_status_service": ("ProviderStatusService", "services.provider_status_service")
}

for file_path in files:
    with open(file_path, 'r') as f:
        content = f.read()

    original_content = content
    imports_to_add = set()

    for factory_name, (type_name, import_path) in FACTORIES.items():
        pattern = r'([ \t]+)(\w+)[ \t]*=[ \t]*' + factory_name + r'\(session\)\n'
        matches = list(re.finditer(pattern, content))
        if not matches:
            continue
            
        imports_to_add.add(f"from {import_path} import {type_name}")
        imports_to_add.add(f"from api.deps import {factory_name}")
        
        # Remove inline imports safely
        content = re.sub(r'^[ \t]+from api\.deps import .*?' + factory_name + r'.*?\n', '', content, flags=re.MULTILINE)
        
        for match in reversed(matches):
            indent = match.group(1)
            var_name = match.group(2)
            
            content = content[:match.start()] + content[match.end():]
            
            def_idx = content.rfind('def ', 0, match.start())
            if def_idx != -1:
                colon_idx = content.find(':', def_idx)
                if colon_idx != -1:
                    signature = content[def_idx:colon_idx]
                    new_dep = f"{var_name}: {type_name} = Depends({factory_name})"
                    
                    if 'session: Session = Depends(get_session)' in signature:
                        new_sig = signature.replace('session: Session = Depends(get_session)', new_dep + ', session: Session = Depends(get_session)')
                        content = content[:def_idx] + new_sig + content[colon_idx:]
                    else:
                        paren_idx = signature.rfind(')')
                        new_sig = signature[:paren_idx] + f", {new_dep}" + signature[paren_idx:]
                        content = content[:def_idx] + new_sig + content[colon_idx:]

    if content != original_content:
        # Cleanup unused sessions function by function
        # Find all functions
        def_matches = list(re.finditer(r'^def (\w+)\((.*?)\)(.*?):', content, flags=re.MULTILINE | re.DOTALL))
        for i in range(len(def_matches)-1, -1, -1):
            match = def_matches[i]
            start = match.end()
            end = def_matches[i+1].start() if i + 1 < len(def_matches) else len(content)
            body = content[start:end]
            
            # If session is in signature but not used in body (checking whole words)
            if 'session: Session = Depends(get_session)' in match.group(2):
                if not re.search(r'\bsession\b', body):
                    # Remove it from signature
                    sig_start = match.start(2)
                    sig_end = match.end(2)
                    sig = content[sig_start:sig_end]
                    sig = re.sub(r',\s*session:\s*Session\s*=\s*Depends\(get_session\)', '', sig)
                    sig = re.sub(r'session:\s*Session\s*=\s*Depends\(get_session\)\s*,?\s*', '', sig)
                    content = content[:sig_start] + sig + content[sig_end:]

        import_block = "\n".join(imports_to_add) + "\n"
        last_import_idx = -1
        for match in re.finditer(r'^(import |from ).*$', content, flags=re.MULTILINE):
            last_import_idx = match.end()
            
        if last_import_idx != -1:
            content = content[:last_import_idx] + "\n" + import_block + content[last_import_idx:]
        else:
            content = import_block + content
            
        with open(file_path, 'w') as f:
            f.write(content)
            
        print(f"Updated {file_path}")

print("Done")
