<?php

namespace App\PromoStandards;

use App\Models\Supplier;
use App\Models\SupplierEndpoint;
use Illuminate\Support\Str;
use InvalidArgumentException;

/**
 * Imports supplier endpoint records from the PromoStandards directory.
 *
 * VERIFY: the directory's real URL and JSON shape could not be checked from the build
 * sandbox. parseJson() tolerates the common key spellings; if the real export differs,
 * adjust parseJson() only. import() works on a normalized array and does not change.
 */
class DirectoryImporter
{
    /**
     * @param  list<array{code: string, name: string, services: list<array{service: string, version: string, url: string}>}>  $records
     * @param  list<string>|null  $onlyCodes  import just these company codes; null = every record
     * @return array{suppliers: int, endpoints: int, skipped_manual: int, unmapped: list<string>}
     */
    public function import(array $records, ?array $onlyCodes = null, bool $activate = true): array
    {
        $stats = ['suppliers' => 0, 'endpoints' => 0, 'skipped_manual' => 0, 'unmapped' => []];
        $only = $onlyCodes === null ? null : array_map('strtolower', $onlyCodes);

        foreach ($records as $record) {
            if ($only !== null && ! in_array(strtolower($record['code']), $only, true)) {
                continue;
            }

            $supplier = Supplier::firstOrNew(['promostandards_code' => $record['code']]);
            if (! $supplier->exists) {
                $supplier->fill([
                    'name' => $record['name'],
                    'slug' => $this->uniqueSlug($record['name']),
                    'type' => 'promostandards',
                    'status' => Supplier::STATUS_DRAFT,
                    // Directory-wide imports stay inactive until someone onboards the supplier on purpose.
                    'is_active' => $activate,
                ])->save();
                $stats['suppliers']++;
            }

            foreach ($record['services'] as $svc) {
                $service = Service::fromDirectoryName($svc['service']);
                if ($service === null) {
                    $stats['unmapped'][] = $svc['service'];

                    continue;
                }

                $endpoint = SupplierEndpoint::firstOrNew([
                    'supplier_id' => $supplier->id, 'service' => $service->value, 'version' => $svc['version'],
                ]);

                // An endpoint a person set by hand always wins over a re-import.
                if ($endpoint->exists && $endpoint->source === SupplierEndpoint::SOURCE_MANUAL) {
                    $stats['skipped_manual']++;

                    continue;
                }

                $endpoint->fill(['url' => $svc['url'], 'source' => SupplierEndpoint::SOURCE_DIRECTORY])->save();
                $stats['endpoints']++;
            }
        }

        $stats['unmapped'] = array_values(array_unique($stats['unmapped']));

        return $stats;
    }

    /** @return list<array{code: string, name: string, services: list<array{service: string, version: string, url: string}>}> */
    public function parseJson(string $json): array
    {
        $data = json_decode($json, true);
        if (! is_array($data)) {
            throw new InvalidArgumentException('Directory file is not valid JSON.');
        }

        // Accept a bare list or a wrapper object like {"Companies": [...]}.
        $list = array_is_list($data) ? $data : ($this->first($data, ['Companies', 'companies', 'Suppliers', 'suppliers', 'Data', 'data']) ?? []);

        $records = [];
        foreach ($list as $row) {
            $code = $this->first($row, ['Code', 'CompanyCode', 'code', 'companyCode', 'Id', 'id']);
            $name = $this->first($row, ['Name', 'CompanyName', 'name', 'companyName']);
            if ($code === null || $name === null) {
                continue;
            }

            $services = [];
            foreach ($this->first($row, ['Services', 'WebServices', 'Endpoints', 'services', 'endpoints']) ?? [] as $s) {
                $type = $this->first($s, ['Type', 'ServiceType', 'Name', 'service', 'type']);
                $version = $this->first($s, ['Version', 'version']);
                $url = $this->first($s, ['URL', 'Url', 'url', 'ProductionURL', 'Endpoint']);
                if ($type !== null && $version !== null && $url !== null) {
                    $services[] = ['service' => (string) $type, 'version' => (string) $version, 'url' => (string) $url];
                }
            }

            $records[] = ['code' => (string) $code, 'name' => (string) $name, 'services' => $services];
        }

        return $records;
    }

    /** @param list<string> $keys */
    private function first(array $row, array $keys): mixed
    {
        foreach ($keys as $key) {
            if (isset($row[$key]) && $row[$key] !== '') {
                return $row[$key];
            }
        }

        return null;
    }

    private function uniqueSlug(string $name): string
    {
        $base = Str::slug($name) ?: 'supplier';
        $slug = $base;
        for ($i = 2; Supplier::where('slug', $slug)->exists(); $i++) {
            $slug = "{$base}-{$i}";
        }

        return $slug;
    }
}
