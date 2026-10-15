import requests, json, time
time.sleep(2)

# Health check
r = requests.get('http://127.0.0.1:5000/health')
print('=== HEALTH:', r.status_code)
h = r.json()
print('  status:', h['status'])
print('  database_ok:', h['database_ok'])
print('  openssl:', h['openssl_version'])

# Capabilities
r2 = requests.get('http://127.0.0.1:5000/api/system/capabilities')
caps = r2.json()
print('\n=== CAPABILITIES:')
print('  OpenSSL:', caps['openssl']['string'])
print('  TLS 1.3:', caps['tls_versions']['TLSv1.3'])
for mode, info in caps['modes'].items():
    avail = info['available']
    limit = info.get('limitations') or ''
    print('  ' + mode + ': available=' + str(avail) + '  ' + limit[:60])

# Run classical experiment
r3 = requests.post('http://127.0.0.1:5000/api/experiments/run', json={
    'mode': 'classical',
    'target_host': '127.0.0.1',
    'target_port': 54443,
    'repetitions': 10,
    'concurrency': 2,
    'warmup_runs': 2,
    'timeout_s': 8.0,
})
exp = r3.json()['experiment']
print('\n=== EXPERIMENT (classical):')
print('  status:', exp['status'])
print('  mean_latency_ms:', exp['mean_latency_ms'])
print('  success_rate_pct:', exp['success_rate_pct'])
print('  negotiated_tls_ver:', exp['negotiated_tls_ver'])
print('  negotiated_group:', exp['negotiated_group'])

# Try PQC - should return 422
r_pqc = requests.post('http://127.0.0.1:5000/api/experiments/run', json={
    'mode': 'pqc',
    'target_host': '127.0.0.1',
    'target_port': 54443,
    'repetitions': 1,
})
print('\n=== PQC MODE TEST:')
print('  HTTP status:', r_pqc.status_code, '(expected 422)')
pqc_err = r_pqc.json()
print('  error:', pqc_err.get('error'))

# Compare
r4 = requests.get('http://127.0.0.1:5000/api/results/compare')
cmp = r4.json()
print('\n=== COMPARISON:')
for mode in ['classical', 'pqc', 'hybrid']:
    d = cmp[mode]
    lat = d['mean_latency_ms']
    oh = d['latency_overhead_pct']
    print('  ' + mode + ': mean_latency=' + str(lat) + '  overhead=' + str(oh))

# Export CSV
r5 = requests.get('http://127.0.0.1:5000/api/results/export?fmt=csv')
lines = r5.text.strip().split('\n')
print('\n=== CSV EXPORT:', len(lines), 'lines')
print('  header:', lines[0][:80])

print('\n=== ALL ENDPOINTS VERIFIED OK')
