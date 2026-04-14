
## Frontend component audit
Before writing any frontend component, run:
  ls frontend/src/components/ui/
Only import primitives that exist in that directory. If a needed component is missing, stop and report it — do not import it anyway. Never assume a shadcn component is installed.
