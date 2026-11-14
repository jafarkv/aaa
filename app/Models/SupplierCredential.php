<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

/**
 * Credential vault. Username and password are encrypted at rest with APP_KEY and hidden
 * from every array/JSON conversion, so they cannot leak through logs, API output or a
 * debug dump. The only way to read them is the explicit attribute access in the SOAP client.
 *
 * If APP_KEY is ever rotated, these rows must be re-encrypted first (php artisan hub:credentials:reencrypt
 * is a Phase 1 task) or every supplier connection stops working.
 */
class SupplierCredential extends Model
{
    protected $fillable = ['supplier_id', 'username', 'password', 'rotated_at'];

    protected $hidden = ['username', 'password'];

    protected function casts(): array
    {
        return [
            'username' => 'encrypted',
            'password' => 'encrypted',
            'rotated_at' => 'datetime',
        ];
    }

    public function supplier(): BelongsTo
    {
        return $this->belongsTo(Supplier::class);
    }
}
