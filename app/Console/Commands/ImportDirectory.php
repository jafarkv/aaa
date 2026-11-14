<?php

namespace App\Console\Commands;

use App\PromoStandards\DirectoryImporter;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Http;

class ImportDirectory extends Command
{
    protected $signature = 'hub:directory:import
        {--file= : Path to a PromoStandards directory JSON export}
        {--url= : Directory URL (defaults to PROMOSTANDARDS_DIRECTORY_URL)}
        {--code=* : Import only these company codes}
        {--all : Import every supplier in the directory (they stay inactive until onboarded)}';

    protected $description = 'Import supplier endpoints from the PromoStandards directory';

    public function handle(DirectoryImporter $importer): int
    {
        $codes = $this->option('code');
        if (! $this->option('all') && $codes === []) {
            $this->error('Pass --code=CODE (repeatable) to import specific suppliers, or --all for the whole directory.');

            return self::FAILURE;
        }

        if ($file = $this->option('file')) {
            if (! is_file($file)) {
                $this->error("File not found: {$file}");

                return self::FAILURE;
            }
            $json = file_get_contents($file);
        } else {
            $url = $this->option('url') ?: config('promostandards.directory_url');
            if (! $url) {
                $this->error('No directory source. Set PROMOSTANDARDS_DIRECTORY_URL, pass --url, or pass --file.');

                return self::FAILURE;
            }
            $response = Http::timeout(60)->get($url);
            if (! $response->successful()) {
                $this->error("Directory request failed with HTTP {$response->status()}.");

                return self::FAILURE;
            }
            $json = $response->body();
        }

        $records = $importer->parseJson($json);
        $stats = $importer->import($records, $this->option('all') ? null : $codes, activate: ! $this->option('all'));

        $this->info("Suppliers created: {$stats['suppliers']}, endpoints written: {$stats['endpoints']}, manual endpoints kept: {$stats['skipped_manual']}.");
        if ($stats['unmapped'] !== []) {
            $this->warn('Service names not recognised (ignored): '.implode(', ', $stats['unmapped']));
        }

        return self::SUCCESS;
    }
}
